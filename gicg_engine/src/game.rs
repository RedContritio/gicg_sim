use std::{collections::VecDeque, rc::Rc};

use rand::{RngExt, SeedableRng, seq::SliceRandom};
use rand_chacha::ChaCha8Rng;
use serde::Deserialize;

use crate::{
    ActionDefinition, ActionTempo, ChoiceOption, Command::*, CounterConsume, Decision, DiceSet,
    Die, Effect, EngineError, EntityRef, Event, EventKind, GameConfig, GameState, HandlerId,
    LuaRuntime, MergePolicy, ModifierState, Phase, PlayerId, Result, RuleContext, Zone,
    lua::resolve_target,
};

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Command {
    Redraw {
        selected: Vec<usize>,
    },
    Reroll {
        payment: DiceSet,
    },
    #[serde(rename = "skill")]
    Skill {
        action: String,
        payment: DiceSet,
    },
    Switch {
        slot: usize,
        payment: DiceSet,
    },
    #[serde(rename = "card")]
    Card {
        hand: usize,
        payment: DiceSet,
    },
    Tune {
        hand: usize,
        die: Die,
    },
    #[serde(rename = "end")]
    End,
}

impl Command {
    fn phase(&self) -> Phase {
        match self {
            Redraw { .. } => Phase::Redraw,
            Reroll { .. } => Phase::Roll,
            Skill { .. } | Switch { .. } | Card { .. } | Tune { .. } | End => Phase::Action,
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

struct QueuedEffect {
    effect: Effect,
    context: RuleContext,
}

#[derive(Clone, Copy)]
struct EventInvocation {
    instance: u32,
    source: EntityRef,
    handler: HandlerId,
}

pub struct Game {
    runtime: Rc<LuaRuntime>,
    pub state: GameState,
    effects: VecDeque<QueuedEffect>,
    active: Option<ActiveAction>,
    rng: ChaCha8Rng,
    first_ended: Option<PlayerId>,
    round_first: PlayerId,
    phase_done: [bool; 2],
}

impl Game {
    pub fn new(runtime: Rc<LuaRuntime>, config: GameConfig) -> Result<Self> {
        let seed = config.seed;
        let first = config.first;
        let mut game = Self {
            state: GameState::new(runtime.rules(), config)?,
            runtime,
            effects: VecDeque::new(),
            active: None,
            rng: ChaCha8Rng::seed_from_u64(seed),
            first_ended: None,
            round_first: first,
            phase_done: [false; 2],
        };
        for player in 0..2 {
            game.state.players[player].deck.shuffle(&mut game.rng);
            game.draw(player, 5);
        }
        Ok(game)
    }

    pub fn rules(&self) -> &crate::Ruleset {
        self.runtime.rules()
    }

    pub fn submit(&mut self, command: Command) -> Result<()> {
        self.validate_command(&command)?;
        let player = self.state.turn;
        match command {
            Redraw { selected } => self.submit_redraw(player, selected),
            Reroll { payment } => self.submit_reroll(player, payment),
            Skill { action, payment } => self.submit_character_action(player, &action, payment),
            Switch { slot, payment } => self.submit_switch(player, slot, payment),
            Card { hand, payment } => self.submit_card(player, hand, payment),
            Tune { hand, die } => self.submit_tune(player, hand, die),
            End => self.submit_end(player),
        }
    }

    fn validate_command(&self, command: &Command) -> Result<()> {
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
        if command.phase() != self.state.phase {
            return Err(EngineError::InvalidCommand(format!(
                "command is not valid during {:?} phase",
                self.state.phase
            )));
        }
        Ok(())
    }

    fn submit_redraw(&mut self, player: PlayerId, mut hand: Vec<usize>) -> Result<()> {
        hand.sort_unstable();
        if hand.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(EngineError::InvalidCommand(
                "redraw contains duplicate hand slots".to_owned(),
            ));
        }
        let player_state = &mut self.state.players[player];
        if hand
            .last()
            .is_some_and(|slot| *slot >= player_state.hand.len())
        {
            return Err(EngineError::InvalidCommand(
                "redraw contains an invalid hand slot".to_owned(),
            ));
        }
        let mut returned = Vec::with_capacity(hand.len());
        for slot in hand.into_iter().rev() {
            returned.push(player_state.hand.remove(slot));
        }
        self.draw(player, returned.len());
        self.state.players[player].deck.extend(returned);
        self.state.players[player].deck.shuffle(&mut self.rng);
        self.finish_shared_phase(player, Phase::Roll)
    }

    fn submit_reroll(&mut self, player: PlayerId, selected: DiceSet) -> Result<()> {
        let inventory = self.state.players[player].dice;
        if Die::ALL
            .iter()
            .any(|die| selected.get(*die) > inventory.get(*die))
        {
            return Err(EngineError::InvalidCommand(
                "reroll selects unavailable dice".to_owned(),
            ));
        }
        for die in Die::ALL {
            self.state.players[player].dice.0[die.index()] -= selected.get(die);
        }
        self.roll(player, usize::from(selected.total()));
        self.finish_shared_phase(player, Phase::Action)
    }

    fn finish_shared_phase(&mut self, player: PlayerId, next: Phase) -> Result<()> {
        self.phase_done[player] = true;
        let opponent = 1 - player;
        if !self.phase_done[opponent] {
            self.state.turn = opponent;
            return Ok(());
        }
        self.phase_done = [false; 2];
        self.state.phase = next;
        self.state.turn = self.round_first;
        if next == Phase::Roll {
            for player in 0..2 {
                if self.state.players[player].dice.total() == 0 {
                    self.roll(player, 8);
                }
            }
        }
        Ok(())
    }

    pub fn choose(&mut self, decision_id: crate::DecisionId, option: usize) -> Result<()> {
        let (decision, selected) = self.take_decision(decision_id, option)?;
        self.force_switch(decision.player, selected)?;
        self.drain()
    }

    fn take_decision(
        &mut self,
        decision_id: crate::DecisionId,
        option: usize,
    ) -> Result<(Decision, ChoiceOption)> {
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
        Ok((decision, selected))
    }

    fn force_switch(&mut self, player: PlayerId, selected: ChoiceOption) -> Result<()> {
        let slot = selected.id.parse::<usize>().map_err(|error| {
            EngineError::Rule(format!(
                "forced switch option {:?} is invalid: {error}",
                selected.id
            ))
        })?;
        let actor = self.state.active_character(player);
        self.state.players[player].active = slot;
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
        })
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
            .character(&character.definition)
            .expect("state references a loaded character");
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

    fn submit_switch(&mut self, player: PlayerId, slot: usize, payment: DiceSet) -> Result<()> {
        let current = self.state.active_character(player);
        if self.state.players[player].active == slot {
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
            tempo: ActionTempo::Combat,
            cost: crate::Cost {
                any: 1,
                ..crate::Cost::default()
            },
            resolve: 0,
        };
        self.pay(current, &switch, payment)?;
        self.state.players[player].active = slot;
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

    fn submit_card(&mut self, player: PlayerId, hand: usize, payment: DiceSet) -> Result<()> {
        let definition_id = self.state.players[player]
            .hand
            .get(hand)
            .ok_or_else(|| EngineError::InvalidCommand(format!("hand slot {hand} is invalid")))?
            .clone();
        let card = self
            .runtime
            .rules()
            .card(&definition_id)
            .expect("hand references a loaded card")
            .clone();
        let actor = self.state.active_character(player);
        self.pay(actor, &card.action, payment)?;
        let removed = self.state.players[player].hand.remove(hand);
        self.state.players[player].discard.push(removed);
        self.active = Some(ActiveAction {
            player,
            actor,
            definition: card.action.clone(),
            emitted_resolved: false,
        });
        self.enqueue_handler(
            card.action.resolve,
            RuleContext {
                actor: Some(actor),
                source: Some(actor),
                action_id: Some(card.id),
                ..RuleContext::default()
            },
        )?;
        self.drain()
    }

    fn submit_tune(&mut self, player: PlayerId, hand: usize, die: Die) -> Result<()> {
        let target = self
            .runtime
            .rules()
            .character(
                &self
                    .state
                    .character(player, self.state.players[player].active)?
                    .definition,
            )
            .expect("loaded character definition exists")
            .element
            .die()
            .ok_or_else(|| EngineError::Rule("physical character cannot tune dice".to_owned()))?;
        if die == target || die == Die::Omni {
            return Err(EngineError::InvalidCommand(
                "selected die cannot be tuned".to_owned(),
            ));
        }
        let state = &mut self.state.players[player];
        if state.dice.get(die) == 0 {
            return Err(EngineError::InvalidCommand(
                "selected die is not available".to_owned(),
            ));
        }
        if hand >= state.hand.len() {
            return Err(EngineError::InvalidCommand(format!(
                "hand slot {hand} is invalid"
            )));
        }
        state.dice.0[die.index()] -= 1;
        state.dice.0[target.index()] += 1;
        let card = state.hand.remove(hand);
        state.discard.push(card);
        Ok(())
    }

    fn submit_end(&mut self, player: PlayerId) -> Result<()> {
        if self.state.players[player].ended {
            return Err(EngineError::InvalidCommand(format!(
                "player {player} has already ended the round"
            )));
        }
        self.state.players[player].ended = true;
        self.first_ended.get_or_insert(player);
        let actor = self.state.active_character(player);
        self.emit(Event {
            kind: EventKind::PlayerEndDeclared,
            actor: Some(actor),
            source: Some(actor),
            target: None,
            player,
            action_id: Some("end_round".to_owned()),
            element: None,
            amount: 0,
        })?;
        self.drain()?;
        let opponent = 1 - player;
        if !self.state.players[opponent].ended {
            self.state.turn = opponent;
            return Ok(());
        }
        self.emit(Event {
            kind: EventKind::RoundEnd,
            actor: None,
            source: None,
            target: None,
            player,
            action_id: None,
            element: None,
            amount: 0,
        })?;
        self.drain()?;
        self.start_round()
    }

    fn start_round(&mut self) -> Result<()> {
        self.state.round = self
            .state
            .round
            .checked_add(1)
            .ok_or_else(|| EngineError::Rule("round counter overflowed".to_owned()))?;
        self.round_first = self.first_ended.take().expect("both players ended");
        self.state.turn = self.round_first;
        self.state.phase = Phase::Roll;
        self.phase_done = [false; 2];
        for player in 0..2 {
            self.state.players[player].ended = false;
            self.state.players[player].dice = DiceSet::default();
            self.draw(player, 2);
            self.roll(player, 8);
        }
        self.emit(Event {
            kind: EventKind::RoundStart,
            actor: None,
            source: None,
            target: None,
            player: self.state.turn,
            action_id: None,
            element: None,
            amount: 0,
        })?;
        self.drain()
    }

    fn draw(&mut self, player: PlayerId, count: usize) {
        let state = &mut self.state.players[player];
        for _ in 0..count {
            let Some(card) = state.deck.pop() else {
                break;
            };
            if state.hand.len() < 10 {
                state.hand.push(card);
            } else {
                state.discard.push(card);
            }
        }
    }

    fn roll(&mut self, player: PlayerId, count: usize) {
        let dice = &mut self.state.players[player].dice;
        for _ in 0..count {
            dice.0[self.rng.random_range(0..Die::COUNT)] += 1;
        }
    }

    fn pay(&mut self, actor: EntityRef, action: &ActionDefinition, payment: DiceSet) -> Result<()> {
        let player = actor.player();
        let inventory = self.state.players[player].dice;
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
        validate_counter_costs(self.state.character(player, slot)?, action)?;
        for die in crate::Die::ALL {
            self.state.players[player].dice.0[die.index()] -= payment.get(die);
        }
        consume_counter_costs(self.state.character_mut(player, slot)?, action);
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
        loop {
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
            if self.state.decision.is_some() {
                return Ok(());
            }
            let Some(active) = &self.active else {
                return Ok(());
            };
            if active.emitted_resolved {
                let active = self.active.take().expect("active action exists");
                if active.definition.tempo == ActionTempo::Combat {
                    let opponent = 1 - active.player;
                    if !self.state.players[opponent].ended {
                        self.state.turn = opponent;
                    }
                }
                return Ok(());
            }
            let active = self.active.as_mut().expect("active action exists");
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
        }
    }

    fn apply(&mut self, queued: QueuedEffect) -> Result<()> {
        match queued.effect {
            Effect::AddCounter {
                target,
                name,
                delta,
            } => self.add_counter(&queued.context, target, &name, delta),
            Effect::Damage {
                target,
                element,
                amount,
            } => self.damage(&queued.context, target, element, amount),
            Effect::AddModifier { target, definition } => {
                self.add_modifier_effect(&queued.context, target, &definition)
            }
        }
    }

    fn add_counter(
        &mut self,
        context: &RuleContext,
        target: crate::TargetRef,
        name: &str,
        delta: i32,
    ) -> Result<()> {
        let target = resolve_target(&self.state, context, target)?;
        let current = self.state.counter(self.runtime.rules(), target, name)?;
        let (min, max) = self
            .state
            .counter_range(self.runtime.rules(), target, name)?;
        let value = current.saturating_add(delta).clamp(min, max);
        self.state
            .set_counter(self.runtime.rules(), target, name, value)?;
        self.remove_exhausted(target)
    }

    fn damage(
        &mut self,
        context: &RuleContext,
        target: crate::TargetRef,
        element: crate::Element,
        amount: u32,
    ) -> Result<()> {
        let target = resolve_target(&self.state, context, target)?;
        let amount = i32::try_from(amount)
            .map_err(|_| EngineError::Rule(format!("damage amount {amount} overflows i32")))?;
        self.apply_damage(context.clone(), target, element, amount)
    }

    fn add_modifier_effect(
        &mut self,
        context: &RuleContext,
        target: crate::TargetRef,
        definition: &str,
    ) -> Result<()> {
        let target = resolve_target(&self.state, context, target)?;
        self.add_modifier(target, definition)
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
        if self.state.players[player].active == slot {
            let options = alive
                .into_iter()
                .map(|slot| ChoiceOption {
                    id: slot.to_string(),
                    label: format!("character:{slot}"),
                })
                .collect();
            self.state.decision = Some(Decision {
                id: self.state.next_decision,
                player,
                options,
            });
            self.state.next_decision += 1;
        }
        Ok(())
    }

    fn add_modifier(&mut self, target: EntityRef, definition_id: &str) -> Result<()> {
        let definition = self
            .runtime
            .rules()
            .modifier(definition_id)
            .ok_or_else(|| {
                EngineError::Rule(format!("modifier definition {definition_id} is missing"))
            })?
            .clone();
        let player = target.player();
        let host = modifier_host(&definition, target)?;
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
            merge_modifier(existing, &definition);
            return Ok(());
        }
        let instance = self.state.next_instance;
        self.state.next_instance += 1;
        self.state
            .modifier_list_mut(player, definition.zone, host)?
            .push(ModifierState {
                instance,
                definition: definition.id.clone(),
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

    fn remove_modifier(&mut self, target: EntityRef) -> Result<()> {
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
            action_id: None,
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
            .modifier(&modifier.definition)
            .expect("state references a loaded modifier");
        if let Some(field) = definition.remove_at_zero
            && self.state.modifier_at(location).counters[field] <= 0
        {
            self.remove_modifier(target)?;
        }
        Ok(())
    }

    fn emit(&mut self, event: Event) -> Result<()> {
        let mut invocations = Vec::new();
        for (player, player_state) in self.state.players.iter().enumerate() {
            for character in &player_state.characters {
                for modifier in &character.modifiers {
                    collect_handlers(
                        &self.runtime,
                        event.kind,
                        player,
                        modifier,
                        &mut invocations,
                    );
                }
            }
            for modifier in player_state
                .combat
                .iter()
                .chain(&player_state.summons)
                .chain(&player_state.supports)
            {
                collect_handlers(
                    &self.runtime,
                    event.kind,
                    player,
                    modifier,
                    &mut invocations,
                );
            }
        }
        invocations.sort_by_key(|invocation| invocation.instance);
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
                },
            )?;
        }
        Ok(())
    }

    fn is_alive(&self, character: EntityRef) -> Result<bool> {
        Ok(self.state.counter(self.runtime.rules(), character, "hp")? > 0)
    }

    fn alive_slots(&self, player: PlayerId) -> Result<Vec<usize>> {
        let mut alive = Vec::new();
        for slot in 0..self.state.players[player].characters.len() {
            if self.is_alive(EntityRef::Character { player, slot })? {
                alive.push(slot);
            }
        }
        Ok(alive)
    }
}

fn validate_counter_costs(
    character: &crate::CharacterState,
    action: &ActionDefinition,
) -> Result<()> {
    for cost in &action.cost.counters {
        let value = character.counters[cost.field];
        if value < cost.require {
            return Err(EngineError::InvalidCommand(format!(
                "action {:?} requires counter value {}, has {}",
                action.id, cost.require, value
            )));
        }
    }
    Ok(())
}

fn consume_counter_costs(character: &mut crate::CharacterState, action: &ActionDefinition) {
    for cost in &action.cost.counters {
        let value = &mut character.counters[cost.field];
        match cost.consume {
            CounterConsume::None => {}
            CounterConsume::Fixed(amount) => *value -= amount,
            CounterConsume::All => *value = 0,
        }
    }
}

fn modifier_host(definition: &crate::ModifierDefinition, target: EntityRef) -> Result<usize> {
    match (definition.zone, target) {
        (Zone::Character, EntityRef::Character { slot, .. }) => Ok(slot),
        (Zone::Character, _) => Err(EngineError::Rule(format!(
            "character modifier {:?} requires a character target",
            definition.id
        ))),
        _ => Ok(0),
    }
}

fn merge_modifier(existing: &mut ModifierState, definition: &crate::ModifierDefinition) {
    if definition.merge == MergePolicy::Replace {
        existing.counters = definition.counters.initial_values();
        return;
    }
    for (index, incoming) in definition.counters.initial_values().into_iter().enumerate() {
        let field = definition
            .counters
            .definition(index)
            .expect("counter field exists");
        let value = match definition.merge {
            MergePolicy::Add => existing.counters[index].saturating_add(incoming),
            MergePolicy::Max => existing.counters[index].max(incoming),
            MergePolicy::Replace | MergePolicy::Independent => unreachable!(),
        };
        existing.counters[index] = value.clamp(field.min, field.max);
    }
}

fn collect_handlers(
    runtime: &LuaRuntime,
    event: EventKind,
    player: PlayerId,
    modifier: &ModifierState,
    output: &mut Vec<EventInvocation>,
) {
    let definition = runtime
        .rules()
        .modifier(&modifier.definition)
        .expect("state references a loaded modifier");
    let Some(&handler) = definition.handlers.get(&event) else {
        return;
    };
    output.push(EventInvocation {
        instance: modifier.instance,
        source: EntityRef::Modifier {
            player,
            instance: modifier.instance,
        },
        handler,
    });
}
