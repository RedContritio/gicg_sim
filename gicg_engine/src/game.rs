use std::{cmp::Ordering, collections::VecDeque};

use crate::{
    ActionDefinition, ActionTempo, ChoiceOption, Command::*, CounterConsume, Decision,
    DecisionKind, DiceSet, Effect, EngineError, EntityRef, Event, EventKind, GameConfig, GameState,
    HandlerId, LuaRuntime, MergePolicy, ModifierState, Phase, PlayerId, RemovalReason, Result,
    RuleContext, Zone, lua::resolve_target,
};

#[derive(Clone, Debug)]
pub enum Command {
    CharacterAction {
        player: PlayerId,
        action: String,
        payment: DiceSet,
    },
    Switch {
        player: PlayerId,
        slot: u8,
        payment: DiceSet,
    },
}

impl Command {
    fn player(&self) -> PlayerId {
        match self {
            CharacterAction { player, .. } | Switch { player, .. } => *player,
        }
    }
}

#[derive(Clone)]
struct ActiveAction {
    player: PlayerId,
    actor: EntityRef,
    definition: ActionDefinition,
    emitted_resolved: bool,
}

struct PendingDecision {
    handler: HandlerId,
    context: RuleContext,
}

struct QueuedEffect {
    effect: Effect,
    context: RuleContext,
}

#[derive(Clone, Copy)]
struct EventInvocation {
    priority: i16,
    instance: u32,
    source: EntityRef,
    handler: HandlerId,
}

pub struct Game<'runtime> {
    runtime: &'runtime LuaRuntime,
    pub state: GameState,
    effects: VecDeque<QueuedEffect>,
    active: Option<ActiveAction>,
    pending: Option<PendingDecision>,
}

impl<'runtime> Game<'runtime> {
    pub fn new(runtime: &'runtime LuaRuntime, config: GameConfig) -> Result<Self> {
        Ok(Self {
            state: GameState::new(runtime.rules(), config)?,
            runtime,
            effects: VecDeque::new(),
            active: None,
            pending: None,
        })
    }

    pub fn submit(&mut self, command: Command) -> Result<()> {
        if self.state.phase != Phase::Action {
            return Err(EngineError::InvalidCommand(
                "game is not accepting actions".to_owned(),
            ));
        }
        if let Some(decision) = &self.state.decision {
            return Err(EngineError::InvalidCommand(format!(
                "decision {} must be answered first",
                decision.id
            )));
        }
        if self.active.is_some() {
            return Err(EngineError::InvalidCommand(
                "an action is already resolving".to_owned(),
            ));
        }
        if command.player() != self.state.turn {
            return Err(EngineError::InvalidCommand(format!(
                "player {} cannot act during player {} turn",
                command.player(),
                self.state.turn
            )));
        }
        match command {
            CharacterAction {
                player,
                action,
                payment,
            } => self.submit_character_action(player, &action, payment),
            Switch {
                player,
                slot,
                payment,
            } => self.submit_switch(player, slot, payment),
        }
    }

    pub fn choose(&mut self, decision_id: crate::DecisionId, option: usize) -> Result<()> {
        let decision = self.state.decision.take().ok_or_else(|| {
            EngineError::InvalidCommand(format!("decision {decision_id} is not active"))
        })?;
        if decision.id != decision_id {
            self.state.decision = Some(decision);
            return Err(EngineError::InvalidCommand(format!(
                "decision {decision_id} is not active"
            )));
        }
        let selected = decision.options.get(option).cloned().ok_or_else(|| {
            EngineError::InvalidCommand(format!(
                "option {option} is invalid for decision {decision_id}"
            ))
        })?;
        match decision.kind {
            DecisionKind::Choice => {
                let pending = self.pending.take().ok_or_else(|| {
                    EngineError::Rule(format!("decision {decision_id} has no continuation"))
                })?;
                let mut context = pending.context;
                context.option = Some(selected.id);
                self.enqueue_handler(pending.handler, context)?;
            }
            DecisionKind::ForcedSwitch => {
                let slot = selected.id.parse::<u8>().map_err(|error| {
                    EngineError::Rule(format!(
                        "forced switch option {:?} is invalid: {error}",
                        selected.id
                    ))
                })?;
                let player = decision.player;
                let actor = self.state.active_character(player);
                self.state.players[usize::from(player)].active = slot;
                let target = self.state.active_character(player);
                self.emit(Event {
                    kind: EventKind::Switch,
                    actor: Some(actor),
                    source: Some(actor),
                    target: Some(target),
                    player,
                    action_id: Some("forced_switch".to_owned()),
                    element: None,
                    amount: 0,
                })?;
            }
        }
        self.drain()
    }

    fn submit_character_action(
        &mut self,
        player: PlayerId,
        action_id: &str,
        payment: DiceSet,
    ) -> Result<()> {
        let actor = self.state.active_character(player);
        let EntityRef::Character { slot, .. } = actor else {
            unreachable!()
        };
        let character = self.state.character(player, slot)?;
        let definition = self
            .runtime
            .rules()
            .character_definition(character.definition)
            .ok_or_else(|| {
                EngineError::Rule(format!(
                    "character definition {} is missing",
                    character.definition
                ))
            })?;
        let action = definition.action(action_id).cloned().ok_or_else(|| {
            EngineError::InvalidCommand(format!(
                "character {:?} has no action {action_id:?}",
                definition.id
            ))
        })?;
        self.pay(actor, &action, payment)?;
        self.active = Some(ActiveAction {
            player,
            actor,
            definition: action.clone(),
            emitted_resolved: false,
        });
        self.enqueue_handler(
            action.resolve,
            RuleContext {
                actor: Some(actor),
                source: Some(actor),
                action_id: Some(action.id),
                ..RuleContext::default()
            },
        )?;
        self.drain()
    }

    fn submit_switch(&mut self, player: PlayerId, slot: u8, payment: DiceSet) -> Result<()> {
        let current = self.state.active_character(player);
        if self.state.players[usize::from(player)].active == slot {
            return Err(EngineError::InvalidCommand(format!(
                "character {player}:{slot} is already active"
            )));
        }
        let target = EntityRef::Character { player, slot };
        if !self.is_alive(target)? {
            return Err(EngineError::InvalidCommand(format!(
                "character {player}:{slot} is defeated"
            )));
        }
        let switch = ActionDefinition {
            id: "switch".to_owned(),
            name: "Switch".to_owned(),
            tags: crate::ActionTags(crate::ActionTags::SWITCH),
            tempo: ActionTempo::Combat,
            cost: crate::Cost {
                any: 1,
                ..crate::Cost::default()
            },
            resolve: 0,
            continuations: Default::default(),
        };
        self.pay(current, &switch, payment)?;
        self.state.players[usize::from(player)].active = slot;
        self.active = Some(ActiveAction {
            player,
            actor: current,
            definition: switch,
            emitted_resolved: false,
        });
        self.emit(Event {
            kind: EventKind::Switch,
            actor: Some(current),
            source: Some(current),
            target: Some(target),
            player,
            action_id: Some("switch".to_owned()),
            element: None,
            amount: 0,
        })?;
        self.drain()
    }

    fn pay(&mut self, actor: EntityRef, action: &ActionDefinition, payment: DiceSet) -> Result<()> {
        let player = actor.player();
        let inventory = self.state.players[usize::from(player)].dice;
        if !action.cost.valid_payment(inventory, payment) {
            return Err(EngineError::InvalidCommand(format!(
                "invalid dice payment for action {:?}",
                action.id
            )));
        }
        let EntityRef::Character { player, slot } = actor else {
            return Err(EngineError::Rule(
                "only characters can pay action costs".to_owned(),
            ));
        };
        let character = self.state.character(player, slot)?;
        for cost in &action.cost.counters {
            let value = character.counters[usize::from(cost.field)];
            if value < cost.require {
                return Err(EngineError::InvalidCommand(format!(
                    "action {:?} requires counter value {}, has {}",
                    action.id, cost.require, value
                )));
            }
        }
        for die in crate::Die::ALL {
            self.state.players[usize::from(player)].dice.0[die.index()] -= payment.get(die);
        }
        let character = self.state.character_mut(player, slot)?;
        for cost in &action.cost.counters {
            match cost.consume {
                CounterConsume::None => {}
                CounterConsume::Fixed(amount) => {
                    character.counters[usize::from(cost.field)] -= amount;
                }
                CounterConsume::All => character.counters[usize::from(cost.field)] = 0,
            }
        }
        Ok(())
    }

    fn enqueue_handler(&mut self, handler: HandlerId, context: RuleContext) -> Result<()> {
        let effects = self.runtime.call(handler, &context, &self.state)?;
        for effect in effects.into_iter().rev() {
            self.effects.push_front(QueuedEffect {
                effect,
                context: context.clone(),
            });
        }
        Ok(())
    }

    fn drain(&mut self) -> Result<()> {
        while self.state.decision.is_none() {
            let Some(effect) = self.effects.pop_front() else {
                break;
            };
            self.apply(effect)?;
            if self.state.phase == Phase::Finished {
                self.effects.clear();
                self.active = None;
                return Ok(());
            }
        }
        if self.state.decision.is_some() || !self.effects.is_empty() {
            return Ok(());
        }
        let Some(active) = &mut self.active else {
            return Ok(());
        };
        if !active.emitted_resolved {
            active.emitted_resolved = true;
            let event = Event {
                kind: EventKind::ActionResolved,
                actor: Some(active.actor),
                source: Some(active.actor),
                target: None,
                player: active.player,
                action_id: Some(active.definition.id.clone()),
                element: None,
                amount: 0,
            };
            self.emit(event)?;
            if !self.effects.is_empty() {
                return self.drain();
            }
        }
        let active = self.active.take().expect("active action exists");
        if active.definition.tempo == ActionTempo::Combat {
            self.state.turn = 1 - active.player;
        }
        Ok(())
    }

    fn apply(&mut self, queued: QueuedEffect) -> Result<()> {
        match queued.effect {
            Effect::SetCounter {
                target,
                name,
                value,
            } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                self.state
                    .set_counter(self.runtime.rules(), target, &name, value)?;
                self.remove_exhausted(target)
            }
            Effect::AddCounter {
                target,
                name,
                delta,
            } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                let current = self.state.counter(self.runtime.rules(), target, &name)?;
                let (min, max) = self
                    .state
                    .counter_range(self.runtime.rules(), target, &name)?;
                let value = current.saturating_add(delta).clamp(min, max);
                self.state
                    .set_counter(self.runtime.rules(), target, &name, value)?;
                self.remove_exhausted(target)
            }
            Effect::Damage {
                target,
                element,
                amount,
            } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                self.apply_damage(queued.context, target, element, amount)
            }
            Effect::AddModifier { target, definition } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                self.add_modifier(target, definition)
            }
            Effect::RemoveModifier { target, reason } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                self.remove_modifier(target, reason)
            }
            Effect::Choice {
                player,
                options,
                continuation,
            } => self.create_choice(player, options, &continuation, queued.context),
            Effect::ActivateAbility { target, ability } => {
                let target = resolve_target(&self.state, &queued.context, target)?;
                self.activate_ability(target, &ability, queued.context)
            }
        }
    }

    fn apply_damage(
        &mut self,
        context: RuleContext,
        target: EntityRef,
        element: crate::Element,
        amount: i32,
    ) -> Result<()> {
        let EntityRef::Character { player, slot } = target else {
            return Err(EngineError::Rule(format!(
                "damage target {target:?} is not a character"
            )));
        };
        let hp = self.state.counter(self.runtime.rules(), target, "hp")?;
        let applied = amount.min(hp);
        self.state
            .set_counter(self.runtime.rules(), target, "hp", hp - applied)?;
        self.emit(Event {
            kind: EventKind::DamageApplied,
            actor: context.actor,
            source: context.source,
            target: Some(target),
            player: context.source.map_or(player, EntityRef::player),
            action_id: context.action_id,
            element: Some(element),
            amount: applied,
        })?;
        if hp - applied > 0 {
            return Ok(());
        }
        let alive = self.alive_slots(player)?;
        if alive.is_empty() {
            self.state.phase = Phase::Finished;
            self.state.winner = Some(1 - player);
            return Ok(());
        }
        if self.state.players[usize::from(player)].active == slot {
            let options = alive
                .into_iter()
                .map(|slot| ChoiceOption {
                    id: slot.to_string(),
                    label: format!("character:{slot}"),
                })
                .collect();
            self.state.decision = Some(Decision {
                id: self.state.next_decision,
                kind: DecisionKind::ForcedSwitch,
                player,
                options,
            });
            self.state.next_decision += 1;
        }
        Ok(())
    }

    fn create_choice(
        &mut self,
        player: PlayerId,
        options: Vec<ChoiceOption>,
        continuation: &str,
        context: RuleContext,
    ) -> Result<()> {
        let active = self
            .active
            .as_ref()
            .ok_or_else(|| EngineError::Rule("choice was created outside an action".to_owned()))?;
        let handler = active
            .definition
            .continuations
            .get(continuation)
            .copied()
            .ok_or_else(|| {
                EngineError::Rule(format!(
                    "action {:?} has no continuation {continuation:?}",
                    active.definition.id
                ))
            })?;
        self.state.decision = Some(Decision {
            id: self.state.next_decision,
            kind: DecisionKind::Choice,
            player,
            options,
        });
        self.state.next_decision += 1;
        self.pending = Some(PendingDecision { handler, context });
        Ok(())
    }

    fn add_modifier(&mut self, target: EntityRef, definition_id: u32) -> Result<()> {
        let definition = self
            .runtime
            .rules()
            .modifier_definition(definition_id)
            .ok_or_else(|| {
                EngineError::Rule(format!("modifier definition {definition_id} is missing"))
            })?
            .clone();
        let player = target.player();
        let host = match (definition.zone, target) {
            (Zone::Character, EntityRef::Character { slot, .. }) => slot,
            (Zone::Character, _) => {
                return Err(EngineError::Rule(format!(
                    "character modifier {:?} requires a character target",
                    definition.id
                )));
            }
            _ => 0,
        };
        let existing_index = if definition.merge == MergePolicy::Independent {
            None
        } else {
            self.state
                .modifier_list_mut(player, definition.zone, host)?
                .iter()
                .position(|modifier| modifier.definition == definition_id)
        };
        if let Some(existing_index) = existing_index {
            let existing = &mut self
                .state
                .modifier_list_mut(player, definition.zone, host)?[existing_index];
            match definition.merge {
                MergePolicy::Replace => {
                    existing.counters = definition.counters.initial_values();
                }
                MergePolicy::Add | MergePolicy::Max => {
                    for (index, incoming) in
                        definition.counters.initial_values().into_iter().enumerate()
                    {
                        let field = definition
                            .counters
                            .definition(index as u16)
                            .expect("counter field exists");
                        let value = if definition.merge == MergePolicy::Add {
                            existing.counters[index].saturating_add(incoming)
                        } else {
                            existing.counters[index].max(incoming)
                        };
                        existing.counters[index] = value.clamp(field.min, field.max);
                    }
                }
                MergePolicy::Independent => unreachable!(),
            }
            return Ok(());
        }
        let instance = self.state.next_instance;
        self.state.next_instance += 1;
        self.state
            .modifier_list_mut(player, definition.zone, host)?
            .push(ModifierState {
                instance,
                definition: definition_id,
                counters: definition.counters.initial_values(),
            });
        let entity = EntityRef::Modifier { player, instance };
        self.emit(Event {
            kind: EventKind::ModifierAdded,
            actor: None,
            source: Some(entity),
            target: Some(entity),
            player,
            action_id: None,
            element: None,
            amount: 0,
        })
    }

    fn remove_modifier(&mut self, target: EntityRef, reason: RemovalReason) -> Result<()> {
        let EntityRef::Modifier { player, instance } = target else {
            return Err(EngineError::Rule(format!(
                "remove target {target:?} is not a modifier"
            )));
        };
        let location = self
            .state
            .find_modifier(instance)
            .map(|(location, _)| location)
            .ok_or_else(|| {
                EngineError::Rule(format!("modifier instance {instance} is not active"))
            })?;
        self.state
            .modifier_list_mut(location.player, location.zone, location.host)?
            .remove(location.index);
        self.emit(Event {
            kind: EventKind::ModifierRemoved,
            actor: None,
            source: Some(target),
            target: Some(target),
            player,
            action_id: Some(format!("reason:{reason:?}")),
            element: None,
            amount: 0,
        })
    }

    fn remove_exhausted(&mut self, target: EntityRef) -> Result<()> {
        let EntityRef::Modifier { instance, .. } = target else {
            return Ok(());
        };
        let Some((location, modifier)) = self.state.find_modifier(instance) else {
            return Ok(());
        };
        let definition = self
            .runtime
            .rules()
            .modifier_definition(modifier.definition)
            .ok_or_else(|| {
                EngineError::Rule(format!(
                    "modifier definition {} is missing",
                    modifier.definition
                ))
            })?;
        if let Some(field) = definition.remove_at_zero
            && self.state.modifier_at(location).counters[usize::from(field)] <= 0
        {
            self.remove_modifier(target, RemovalReason::Exhausted)?;
        }
        Ok(())
    }

    fn activate_ability(
        &mut self,
        target: EntityRef,
        ability: &str,
        mut context: RuleContext,
    ) -> Result<()> {
        let EntityRef::Modifier { instance, .. } = target else {
            return Err(EngineError::Rule(format!(
                "ability target {target:?} is not a modifier"
            )));
        };
        let (_, modifier) = self.state.find_modifier(instance).ok_or_else(|| {
            EngineError::Rule(format!("modifier instance {instance} is not active"))
        })?;
        let definition = self
            .runtime
            .rules()
            .modifier_definition(modifier.definition)
            .ok_or_else(|| {
                EngineError::Rule(format!(
                    "modifier definition {} is missing",
                    modifier.definition
                ))
            })?;
        let handler = definition.abilities.get(ability).copied().ok_or_else(|| {
            EngineError::Rule(format!(
                "modifier {:?} has no ability {ability:?}",
                definition.id
            ))
        })?;
        context.source = Some(target);
        self.enqueue_handler(handler, context)
    }

    fn emit(&mut self, event: Event) -> Result<()> {
        let mut invocations = Vec::new();
        for (player, player_state) in self.state.players.iter().enumerate() {
            let player = player as PlayerId;
            for character in &player_state.characters {
                for modifier in &character.modifiers {
                    collect_handlers(self.runtime, event.kind, player, modifier, &mut invocations);
                }
            }
            for modifier in player_state
                .combat
                .iter()
                .chain(&player_state.summons)
                .chain(&player_state.supports)
            {
                collect_handlers(self.runtime, event.kind, player, modifier, &mut invocations);
            }
        }
        invocations.sort_by(|left, right| match left.priority.cmp(&right.priority) {
            Ordering::Equal => left.instance.cmp(&right.instance),
            ordering => ordering,
        });
        for invocation in invocations {
            if self.state.find_modifier(invocation.instance).is_none() {
                continue;
            }
            self.enqueue_handler(
                invocation.handler,
                RuleContext {
                    actor: event.actor,
                    source: Some(invocation.source),
                    target: event.target,
                    event: Some(event.clone()),
                    action_id: event.action_id.clone(),
                    option: None,
                },
            )?;
        }
        Ok(())
    }

    fn is_alive(&self, character: EntityRef) -> Result<bool> {
        Ok(self.state.counter(self.runtime.rules(), character, "hp")? > 0)
    }

    fn alive_slots(&self, player: PlayerId) -> Result<Vec<u8>> {
        let mut alive = Vec::new();
        for slot in 0..self.state.players[usize::from(player)].characters.len() {
            let slot = u8::try_from(slot).map_err(|_| {
                EngineError::Rule("a player has more than 255 characters".to_owned())
            })?;
            if self.is_alive(EntityRef::Character { player, slot })? {
                alive.push(slot);
            }
        }
        Ok(alive)
    }
}

fn collect_handlers(
    runtime: &LuaRuntime,
    event: EventKind,
    player: PlayerId,
    modifier: &ModifierState,
    output: &mut Vec<EventInvocation>,
) {
    let Some(definition) = runtime.rules().modifier_definition(modifier.definition) else {
        return;
    };
    let Some(handlers) = definition.handlers.get(&event) else {
        return;
    };
    for handler in handlers {
        output.push(EventInvocation {
            priority: handler.priority,
            instance: modifier.instance,
            source: EntityRef::Modifier {
                player,
                instance: modifier.instance,
            },
            handler: handler.handler,
        });
    }
}
