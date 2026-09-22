use std::{collections::VecDeque, rc::Rc};

use rand::{RngExt, SeedableRng, seq::SliceRandom};
use rand_chacha::ChaCha8Rng;
use serde::{Deserialize, Serialize};

use crate::{
    ActionDefinition, ActionKind, ActionModifierDefinition, ActionTempo, CharacterTargetDefinition,
    ChoiceOption,
    Command::*,
    CounterConsume, DamageDirection, DamageModifierDefinition, Decision, DiceSet, Die, Effect,
    Element, EngineError, EntityRef, Event, EventKind, GameConfig, GameState, HandlerId,
    LuaRuntime, MergePolicy, ModifierState, Phase, PlayerId, Reaction, ReactionRecord, Result,
    RuleContext, TargetSide, TargetState, Zone,
    lua::resolve_target,
    reaction::{self, FROZEN},
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
    Concede,
}

impl Command {
    fn phase(&self) -> Option<Phase> {
        match self {
            Redraw { .. } => Some(Phase::Redraw),
            Reroll { .. } => Some(Phase::Roll),
            Skill { .. } | Switch { .. } | Card { .. } | Tune { .. } | End => Some(Phase::Action),
            Concede => None,
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

enum PendingDecision {
    InitialActive,
    Continuation {
        handler: HandlerId,
        context: RuleContext,
    },
    ModifierReplacement {
        target: EntityRef,
        definition: String,
    },
    CardTarget {
        handler: HandlerId,
        context: RuleContext,
        player: PlayerId,
    },
}

struct DamageResolution {
    amount: i32,
    element: Element,
    reaction: Option<reaction::ReactionMatch>,
}

struct DamageInvocation {
    source: EntityRef,
    host: Option<EntityRef>,
    rule: DamageModifierDefinition,
}

struct ActionInvocation {
    source: EntityRef,
    host: Option<EntityRef>,
    rule: ActionModifierDefinition,
}

struct ActionConsumption {
    source: EntityRef,
    counter: String,
    amount: i32,
}

#[derive(Clone, Copy)]
struct EventInvocation {
    instance: u32,
    source: EntityRef,
    handler: HandlerId,
}

#[derive(Clone, Debug, Serialize)]
pub struct ActionPreview {
    pub id: String,
    pub tempo: ActionTempo,
    pub dice: DiceSet,
    pub any: u8,
    pub playable: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct PlayerActionPreviews {
    pub skills: Vec<ActionPreview>,
    pub switch: ActionPreview,
    pub cards: Vec<ActionPreview>,
}

pub struct Game {
    runtime: Rc<LuaRuntime>,
    pub state: GameState,
    effects: VecDeque<QueuedEffect>,
    active: Option<ActiveAction>,
    pending: Option<PendingDecision>,
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
            pending: None,
            rng: ChaCha8Rng::seed_from_u64(seed),
            first_ended: None,
            round_first: first,
            phase_done: [false; 2],
        };
        for player in 0..2 {
            game.state.players[player].deck.shuffle(&mut game.rng);
            game.draw(player, 5)?;
        }
        if game.state.phase == Phase::SelectActive {
            game.create_initial_active_decision(first);
        }
        Ok(game)
    }

    pub fn rules(&self) -> &crate::Ruleset {
        self.runtime.rules()
    }

    pub fn action_previews(&self) -> Result<[PlayerActionPreviews; 2]> {
        Ok([
            self.player_action_previews(0)?,
            self.player_action_previews(1)?,
        ])
    }

    fn player_action_previews(&self, player: PlayerId) -> Result<PlayerActionPreviews> {
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
        let skills = definition
            .actions
            .iter()
            .cloned()
            .map(|action| self.preview_action(actor, ActionKind::Skill, action))
            .collect::<Result<Vec<_>>>()?;
        let switch = self.preview_action(actor, ActionKind::Switch, switch_action())?;
        let cards = self.state.players[player]
            .hand
            .iter()
            .map(|id| {
                let card = self
                    .runtime
                    .rules()
                    .card(id)
                    .expect("hand references a loaded card");
                let mut preview =
                    self.preview_action(actor, ActionKind::Card, card.action.clone())?;
                preview.playable = card
                    .target
                    .as_ref()
                    .is_none_or(|target| !self.card_targets(player, target).is_empty());
                Ok(preview)
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(PlayerActionPreviews {
            skills,
            switch,
            cards,
        })
    }

    fn preview_action(
        &self,
        actor: EntityRef,
        kind: ActionKind,
        action: ActionDefinition,
    ) -> Result<ActionPreview> {
        let (action, _) = self.prepare_action(actor, kind, action)?;
        Ok(ActionPreview {
            id: action.id,
            tempo: action.tempo,
            dice: action.cost.dice,
            any: action.cost.any,
            playable: true,
        })
    }

    pub fn submit(&mut self, command: Command) -> Result<()> {
        self.validate_command(&command)?;
        let previous_reaction = self.state.last_reaction.take();
        let player = self
            .state
            .decision
            .as_ref()
            .map_or(self.state.turn, |decision| decision.player);
        let result = match command {
            Redraw { selected } => self.submit_redraw(player, selected),
            Reroll { payment } => self.submit_reroll(player, payment),
            Skill { action, payment } => self.submit_character_action(player, &action, payment),
            Switch { slot, payment } => self.submit_switch(player, slot, payment),
            Card { hand, payment } => self.submit_card(player, hand, payment),
            Tune { hand, die } => self.submit_tune(player, hand, die),
            End => self.submit_end(player),
            Concede => self.submit_concede(player),
        };
        if result.is_err() {
            self.state.last_reaction = previous_reaction;
        }
        result
    }

    fn validate_command(&self, command: &Command) -> Result<()> {
        if matches!(command, Concede) {
            return (self.state.phase != Phase::Finished)
                .then_some(())
                .ok_or_else(|| {
                    EngineError::InvalidCommand("match is already finished".to_owned())
                });
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
        if command.phase() != Some(self.state.phase) {
            return Err(EngineError::InvalidCommand(format!(
                "command is not valid during {:?} phase",
                self.state.phase
            )));
        }
        Ok(())
    }

    fn submit_concede(&mut self, player: PlayerId) -> Result<()> {
        self.state.history.push(Event {
            kind: EventKind::Conceded,
            actor: None,
            source: None,
            target: None,
            player,
            action_id: Some("concede".to_owned()),
            element: None,
            reaction: None,
            amount: 0,
        });
        self.finish_match(1 - player, crate::FinishReason::Concede);
        Ok(())
    }

    fn finish_match(&mut self, winner: PlayerId, reason: crate::FinishReason) {
        self.state.phase = Phase::Finished;
        self.state.winner = Some(winner);
        self.state.finish_reason = Some(reason);
        self.state.decision = None;
        self.effects.clear();
        self.active = None;
        self.pending = None;
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
        self.draw(player, returned.len())?;
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
        match self.pending.take() {
            Some(PendingDecision::InitialActive) => {
                self.select_initial_active(decision.player, selected)?;
            }
            Some(PendingDecision::Continuation { handler, context }) => {
                self.continue_choice(handler, context, selected)?;
            }
            Some(PendingDecision::ModifierReplacement { target, definition }) => {
                self.replace_modifier(decision.player, selected, target, &definition)?;
            }
            Some(PendingDecision::CardTarget {
                handler,
                context,
                player,
            }) => self.continue_card_target(handler, context, player, selected)?,
            None => self.force_switch(decision.player, selected)?,
        }
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
        let Some(selected) = decision.options.get(option).cloned() else {
            self.state.decision = Some(decision);
            return Err(EngineError::InvalidCommand(format!(
                "option {option} is invalid for decision {decision_id}"
            )));
        };
        Ok((decision, selected))
    }

    fn create_initial_active_decision(&mut self, player: PlayerId) {
        let options = self.state.players[player]
            .characters
            .iter()
            .enumerate()
            .map(|(slot, character)| ChoiceOption {
                id: slot.to_string(),
                label: self
                    .runtime
                    .rules()
                    .character(&character.definition)
                    .expect("state references a loaded character")
                    .name
                    .clone(),
            })
            .collect();
        self.state.decision = Some(Decision {
            id: self.state.next_decision,
            player,
            options,
        });
        self.state.next_decision += 1;
        self.pending = Some(PendingDecision::InitialActive);
    }

    fn select_initial_active(&mut self, player: PlayerId, selected: ChoiceOption) -> Result<()> {
        let slot = selected.id.parse::<usize>().map_err(|error| {
            EngineError::Rule(format!("invalid initial character option: {error}"))
        })?;
        self.state.character(player, slot)?;
        self.state.players[player].active = slot;
        self.phase_done[player] = true;
        let opponent = 1 - player;
        if !self.phase_done[opponent] {
            self.state.turn = opponent;
            self.create_initial_active_decision(opponent);
            return Ok(());
        }
        self.phase_done = [false; 2];
        self.state.phase = Phase::Redraw;
        self.state.turn = self.round_first;
        Ok(())
    }

    fn continue_choice(
        &mut self,
        handler: HandlerId,
        mut context: RuleContext,
        selected: ChoiceOption,
    ) -> Result<()> {
        context.option = Some(selected.id);
        self.enqueue_handler(handler, context)
    }

    fn continue_card_target(
        &mut self,
        handler: HandlerId,
        mut context: RuleContext,
        player: PlayerId,
        selected: ChoiceOption,
    ) -> Result<()> {
        let slot = selected
            .id
            .parse::<usize>()
            .map_err(|error| EngineError::Rule(format!("invalid card target option: {error}")))?;
        self.state.character(player, slot)?;
        context.target = Some(EntityRef::Character { player, slot });
        self.enqueue_handler(handler, context)
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
            reaction: None,
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
        if self
            .state
            .character_modifier_entity(player, slot, FROZEN)
            .is_some()
        {
            return Err(EngineError::InvalidCommand(
                "frozen character cannot use an action".to_owned(),
            ));
        }
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
        let (action, consumptions) = self.prepare_action(actor, ActionKind::Skill, action)?;
        self.pay(actor, &action, payment)?;
        self.consume_action_modifiers(consumptions)?;
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
        let switch = switch_action();
        let (switch, consumptions) = self.prepare_action(current, ActionKind::Switch, switch)?;
        self.pay(current, &switch, payment)?;
        self.consume_action_modifiers(consumptions)?;
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
            reaction: None,
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
        let targets = card
            .target
            .as_ref()
            .map(|target| self.card_targets(player, target));
        if targets.as_ref().is_some_and(Vec::is_empty) {
            return Err(EngineError::InvalidCommand(format!(
                "card {:?} has no legal target",
                card.id
            )));
        }
        let actor = self.state.active_character(player);
        let (action, consumptions) =
            self.prepare_action(actor, ActionKind::Card, card.action.clone())?;
        self.pay(actor, &action, payment)?;
        self.consume_action_modifiers(consumptions)?;
        let removed = self.state.players[player].hand.remove(hand);
        self.state.players[player].discard.push(removed);
        self.active = Some(ActiveAction {
            player,
            actor,
            definition: action.clone(),
            emitted_resolved: false,
        });
        let context = RuleContext {
            actor: Some(actor),
            source: Some(actor),
            action_id: Some(card.id),
            ..RuleContext::default()
        };
        if let Some(targets) = targets {
            self.create_card_target_choice(targets, action.resolve, context);
        } else {
            self.enqueue_handler(action.resolve, context)?;
        }
        self.drain()
    }

    fn card_targets(&self, player: PlayerId, target: &CharacterTargetDefinition) -> Vec<EntityRef> {
        let owner = match target.side {
            TargetSide::Own => player,
            TargetSide::Enemy => 1 - player,
        };
        (0..self.state.players[owner].characters.len())
            .map(|slot| EntityRef::Character {
                player: owner,
                slot,
            })
            .filter(|character| self.card_target_matches(*character, target))
            .collect()
    }

    fn card_target_matches(
        &self,
        character: EntityRef,
        target: &CharacterTargetDefinition,
    ) -> bool {
        let hp = self
            .state
            .counter(self.runtime.rules(), character, "hp")
            .expect("character has hp");
        let state_matches = match target.state {
            TargetState::Alive => hp > 0,
            TargetState::Defeated => hp == 0,
            TargetState::Any => true,
        };
        let active_matches = !target.active_only
            || self.state.players[character.player()].active == character_slot(character);
        let damaged_matches = !target.damaged
            || self
                .state
                .counter_range(self.runtime.rules(), character, "hp")
                .is_ok_and(|(_, maximum)| hp < maximum);
        state_matches && active_matches && damaged_matches
    }

    fn create_card_target_choice(
        &mut self,
        targets: Vec<EntityRef>,
        handler: HandlerId,
        context: RuleContext,
    ) {
        let player = targets[0].player();
        let options = targets
            .into_iter()
            .map(|target| ChoiceOption {
                id: character_slot(target).to_string(),
                label: self.character_name(target).to_owned(),
            })
            .collect();
        self.state.decision = Some(Decision {
            id: self.state.next_decision,
            player: context.actor.expect("card has actor").player(),
            options,
        });
        self.state.next_decision += 1;
        self.pending = Some(PendingDecision::CardTarget {
            handler,
            context,
            player,
        });
    }

    fn character_name(&self, target: EntityRef) -> &str {
        let EntityRef::Character { player, slot } = target else {
            unreachable!()
        };
        let character = &self.state.players[player].characters[slot];
        &self
            .runtime
            .rules()
            .character(&character.definition)
            .expect("state references a loaded character")
            .name
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
            reaction: None,
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
            reaction: None,
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
            self.draw(player, 2)?;
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
            reaction: None,
            amount: 0,
        })?;
        self.drain()
    }

    fn draw(&mut self, player: PlayerId, count: usize) -> Result<()> {
        for _ in 0..count {
            if !self.draw_one(player)? {
                break;
            }
            self.drain()?;
        }
        Ok(())
    }

    fn draw_one(&mut self, player: PlayerId) -> Result<bool> {
        let Some(card) = self.state.players[player].deck.pop() else {
            return Ok(false);
        };
        if self.state.players[player].hand.len() < 10 {
            self.state.players[player].hand.push(card.clone());
            self.emit_card_event(EventKind::CardDrawn, player, card)?;
        } else {
            self.state.players[player].discard.push(card.clone());
            self.emit_card_event(EventKind::CardDiscarded, player, card)?;
        }
        Ok(true)
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

    fn prepare_action(
        &self,
        actor: EntityRef,
        kind: ActionKind,
        mut action: ActionDefinition,
    ) -> Result<(ActionDefinition, Vec<ActionConsumption>)> {
        let mut consumptions = Vec::new();
        for invocation in self.action_invocations(actor.player()) {
            if !self.action_rule_applies(&invocation, actor, kind, &action.id)? {
                continue;
            }
            let changed = apply_action_rule(&mut action, &invocation.rule);
            if changed && let Some(counter) = invocation.rule.counter {
                consumptions.push(ActionConsumption {
                    source: invocation.source,
                    counter,
                    amount: invocation.rule.consume,
                });
            }
        }
        Ok((action, consumptions))
    }

    fn action_rule_applies(
        &self,
        invocation: &ActionInvocation,
        actor: EntityRef,
        kind: ActionKind,
        action: &str,
    ) -> Result<bool> {
        if invocation.host.is_some_and(|host| host != actor) {
            return Ok(false);
        }
        if !invocation.rule.kinds.is_empty() && !invocation.rule.kinds.contains(&kind) {
            return Ok(false);
        }
        if !invocation.rule.actions.is_empty()
            && !invocation.rule.actions.iter().any(|value| value == action)
        {
            return Ok(false);
        }
        let Some(counter) = &invocation.rule.counter else {
            return Ok(true);
        };
        Ok(self
            .state
            .counter(self.runtime.rules(), invocation.source, counter)?
            > 0)
    }

    fn action_invocations(&self, player: PlayerId) -> Vec<ActionInvocation> {
        let state = &self.state.players[player];
        let mut invocations = Vec::new();
        for (slot, character) in state.characters.iter().enumerate() {
            for modifier in &character.modifiers {
                collect_action_rule(
                    &self.runtime,
                    player,
                    Some(EntityRef::Character { player, slot }),
                    modifier,
                    &mut invocations,
                );
            }
        }
        for modifier in state
            .combat
            .iter()
            .chain(&state.summons)
            .chain(&state.supports)
        {
            collect_action_rule(&self.runtime, player, None, modifier, &mut invocations);
        }
        invocations.sort_by_key(|value| modifier_instance(value.source));
        invocations
    }

    fn consume_action_modifiers(&mut self, consumptions: Vec<ActionConsumption>) -> Result<()> {
        for consumption in consumptions {
            self.add_entity_counter(
                consumption.source,
                &consumption.counter,
                -consumption.amount,
            )?;
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
                reaction: None,
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
            Effect::Heal { target, amount } => self.heal(&queued.context, target, amount),
            Effect::AddModifier { target, definition } => {
                self.add_modifier_effect(&queued.context, target, &definition)
            }
            Effect::AddModifierCounter {
                definition,
                name,
                delta,
            } => self.add_modifier_counter(&queued.context, &definition, &name, delta),
            Effect::AddCharacterCounter {
                character,
                name,
                delta,
            } => self.add_character_counter(&queued.context, &character, &name, delta),
            Effect::RemoveModifier { definition } => {
                self.remove_modifier_definition(&queued.context, &definition)
            }
            Effect::AddCard { card } => self.add_card(&queued.context, &card),
            Effect::AddDice { die, count } => self.add_dice(&queued.context, die, count),
            Effect::Draw { count } => self.draw_effect(queued.context, count),
            Effect::Discard { side, count } => {
                self.discard(&queued.context, side, usize::from(count))
            }
            Effect::Choice {
                options,
                continuation,
            } => self.create_choice(options, &continuation, queued.context),
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
        self.add_entity_counter(target, name, delta)
    }

    fn add_entity_counter(&mut self, target: EntityRef, name: &str, delta: i32) -> Result<()> {
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

    fn heal(&mut self, context: &RuleContext, target: crate::TargetRef, amount: u32) -> Result<()> {
        let target = resolve_target(&self.state, context, target)?;
        let EntityRef::Character { player, .. } = target else {
            return Err(EngineError::Rule(format!(
                "healing target {target:?} is not a character"
            )));
        };
        let hp = self.state.counter(self.runtime.rules(), target, "hp")?;
        if hp <= 0 {
            return Err(EngineError::Rule(
                "cannot heal a defeated character".to_owned(),
            ));
        }
        let (_, maximum) = self
            .state
            .counter_range(self.runtime.rules(), target, "hp")?;
        let amount = i32::try_from(amount)
            .map_err(|_| EngineError::Rule(format!("healing amount {amount} overflows i32")))?;
        let healed = amount.min(maximum - hp);
        self.state
            .set_counter(self.runtime.rules(), target, "hp", hp + healed)?;
        self.emit(Event {
            kind: EventKind::Healed,
            actor: context.actor,
            source: context.source,
            target: Some(target),
            player: context.source.map_or(player, EntityRef::player),
            action_id: context.action_id.clone(),
            element: None,
            reaction: None,
            amount: healed,
        })
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

    fn add_modifier_counter(
        &mut self,
        context: &RuleContext,
        definition: &str,
        name: &str,
        delta: i32,
    ) -> Result<()> {
        let player = context_owner(context)?;
        let target = self
            .state
            .modifier_entity(player, definition)
            .ok_or_else(|| EngineError::Rule(format!("modifier {definition:?} is not active")))?;
        self.add_entity_counter(target, name, delta)
    }

    fn add_character_counter(
        &mut self,
        context: &RuleContext,
        character: &str,
        name: &str,
        delta: i32,
    ) -> Result<()> {
        let player = context_owner(context)?;
        let target = self
            .state
            .character_entity(player, character)
            .ok_or_else(|| EngineError::Rule(format!("character {character:?} is not active")))?;
        self.add_entity_counter(target, name, delta)
    }

    fn remove_modifier_definition(
        &mut self,
        context: &RuleContext,
        definition: &str,
    ) -> Result<()> {
        let player = context_owner(context)?;
        let target = self
            .state
            .modifier_entity(player, definition)
            .ok_or_else(|| EngineError::Rule(format!("modifier {definition:?} is not active")))?;
        self.remove_modifier(target)
    }

    fn add_card(&mut self, context: &RuleContext, card: &str) -> Result<()> {
        if self.runtime.rules().card(card).is_none() {
            return Err(EngineError::Rule(format!("card {card:?} is not defined")));
        }
        let state = &mut self.state.players[context_owner(context)?];
        if state.hand.len() < 10 {
            state.hand.push(card.to_owned());
        } else {
            state.discard.push(card.to_owned());
        }
        Ok(())
    }

    fn add_dice(&mut self, context: &RuleContext, die: Die, count: u8) -> Result<()> {
        let dice = &mut self.state.players[context_owner(context)?].dice.0[die.index()];
        *dice = dice
            .checked_add(count)
            .ok_or_else(|| EngineError::Rule("dice count overflowed".to_owned()))?;
        Ok(())
    }

    fn discard(&mut self, context: &RuleContext, side: TargetSide, count: usize) -> Result<()> {
        let owner = context_owner(context)?;
        let player = match side {
            TargetSide::Own => owner,
            TargetSide::Enemy => 1 - owner,
        };
        for _ in 0..count.min(self.state.players[player].hand.len()) {
            let index = self
                .rng
                .random_range(0..self.state.players[player].hand.len());
            let card = self.state.players[player].hand.remove(index);
            self.state.players[player].discard.push(card.clone());
            self.emit_card_event(EventKind::CardDiscarded, player, card)?;
        }
        Ok(())
    }

    fn draw_effect(&mut self, context: RuleContext, count: u8) -> Result<()> {
        if count == 0 {
            return Ok(());
        }
        if count > 1 {
            self.effects.push_front(QueuedEffect {
                effect: Effect::Draw { count: count - 1 },
                context: context.clone(),
            });
        }
        self.draw_one(context_owner(&context)?)?;
        Ok(())
    }

    fn emit_card_event(&mut self, kind: EventKind, player: PlayerId, card: String) -> Result<()> {
        self.emit(Event {
            kind,
            actor: None,
            source: None,
            target: None,
            player,
            action_id: Some(card),
            element: None,
            reaction: None,
            amount: 1,
        })
    }

    fn apply_damage(
        &mut self,
        context: RuleContext,
        target: EntityRef,
        element: Element,
        amount: i32,
    ) -> Result<()> {
        let EntityRef::Character { player, .. } = target else {
            return Err(EngineError::Rule(format!(
                "damage target {target:?} is not a character"
            )));
        };
        let resolved = self.prepare_damage(&context, target, element, amount)?;
        let applied = self.commit_damage(&context, target, &resolved)?;
        self.finish_damage(context, target, player, resolved, applied)
    }

    fn prepare_damage(
        &mut self,
        context: &RuleContext,
        target: EntityRef,
        element: Element,
        amount: i32,
    ) -> Result<DamageResolution> {
        let (element, amount) = self.apply_damage_modifiers(
            DamageDirection::Outgoing,
            context,
            target,
            element,
            amount,
        )?;
        let reaction = self.resolve_reaction(target, element)?;
        let reaction_bonus = reaction.map_or(0, |value| value.kind.bonus());
        let boosted = amount.saturating_add(reaction_bonus);
        let (element, amount) = self.apply_damage_modifiers(
            DamageDirection::Incoming,
            context,
            target,
            element,
            boosted,
        )?;
        Ok(DamageResolution {
            amount,
            element,
            reaction,
        })
    }

    fn commit_damage(
        &mut self,
        context: &RuleContext,
        target: EntityRef,
        resolved: &DamageResolution,
    ) -> Result<i32> {
        let EntityRef::Character { player, slot } = target else {
            unreachable!()
        };
        let hp = self.state.counter(self.runtime.rules(), target, "hp")?;
        let applied = resolved.amount.min(hp);
        self.state
            .set_counter(self.runtime.rules(), target, "hp", hp - applied)?;
        let reaction_kind = resolved.reaction.map(|value| value.kind);
        if let Some(kind) = reaction_kind {
            self.state.last_reaction = Some(ReactionRecord { kind, player, slot });
        }
        self.emit(Event {
            kind: EventKind::DamageApplied,
            actor: context.actor,
            source: context.source,
            target: Some(target),
            player: context.source.map_or(player, EntityRef::player),
            action_id: context.action_id.clone(),
            element: Some(resolved.element),
            reaction: reaction_kind,
            amount: applied,
        })?;
        Ok(applied)
    }

    fn finish_damage(
        &mut self,
        context: RuleContext,
        target: EntityRef,
        player: PlayerId,
        resolved: DamageResolution,
        applied: i32,
    ) -> Result<()> {
        let hp = self.state.counter(self.runtime.rules(), target, "hp")?;
        let defeated = hp <= 0 && applied > 0;
        let reaction_kind = resolved.reaction.map(|value| value.kind);
        if defeated {
            self.handle_defeat(target, reaction_kind.is_some_and(Reaction::force_switch))?;
        }
        if self.state.phase == Phase::Finished {
            return Ok(());
        }
        self.finish_reaction(&context, target, player, resolved.reaction, defeated)
    }

    fn finish_reaction(
        &mut self,
        context: &RuleContext,
        target: EntityRef,
        player: PlayerId,
        reaction: Option<reaction::ReactionMatch>,
        defeated: bool,
    ) -> Result<()> {
        if let Some(reaction) = reaction {
            self.apply_reaction_result(context, target, reaction, defeated)?;
            if reaction.kind.force_switch() && !defeated {
                self.switch_next(player)?;
            }
        }
        Ok(())
    }

    fn resolve_reaction(
        &mut self,
        target: EntityRef,
        element: Element,
    ) -> Result<Option<reaction::ReactionMatch>> {
        let EntityRef::Character { player, slot } = target else {
            unreachable!()
        };
        if matches!(element, Element::Physical | Element::Pyro)
            && let Some(frozen) = self.state.character_modifier_entity(player, slot, FROZEN)
        {
            self.remove_modifier(frozen)?;
            return Ok(Some(reaction::ReactionMatch {
                kind: Reaction::Shatter,
                aura: element,
            }));
        }
        let matched = reaction::resolve(&self.state.character(player, slot)?.auras, element);
        let character = self.state.character_mut(player, slot)?;
        if let Some(value) = matched {
            character.auras.retain(|aura| *aura != value.aura);
        } else if element.attaches() && !character.auras.contains(&element) {
            character.auras.push(element);
        }
        Ok(matched)
    }

    fn apply_damage_modifiers(
        &mut self,
        direction: DamageDirection,
        context: &RuleContext,
        target: EntityRef,
        mut element: Element,
        mut amount: i32,
    ) -> Result<(Element, i32)> {
        for invocation in self.damage_invocations() {
            if !self.damage_rule_applies(&invocation, direction, context, target, element)? {
                continue;
            }
            if let Some(counter) = &invocation.rule.shield {
                let points =
                    self.state
                        .counter(self.runtime.rules(), invocation.source, counter)?;
                let absorbed = points.min(amount);
                amount -= absorbed;
                self.add_entity_counter(invocation.source, counter, -absorbed)?;
                continue;
            }
            amount = amount.saturating_add(invocation.rule.delta).max(0);
            if let Some(value) = invocation.rule.set_element {
                element = value;
            }
            if let Some(counter) = &invocation.rule.counter {
                self.add_entity_counter(invocation.source, counter, -invocation.rule.consume)?;
            }
        }
        Ok((element, amount))
    }

    fn damage_rule_applies(
        &self,
        invocation: &DamageInvocation,
        direction: DamageDirection,
        context: &RuleContext,
        target: EntityRef,
        element: Element,
    ) -> Result<bool> {
        if invocation.rule.direction != direction {
            return Ok(false);
        }
        if !damage_element_matches(&invocation.rule, element) {
            return Ok(false);
        }
        let owner = invocation.source.player();
        if !damage_owner_matches(direction, owner, context.source, target) {
            return Ok(false);
        }
        if !damage_host_matches(invocation.host, direction, context.actor, target) {
            return Ok(false);
        }
        if invocation.rule.active_only && !self.is_active_target(target) {
            return Ok(false);
        }
        if let Some(counter) = &invocation.rule.counter {
            return Ok(self
                .state
                .counter(self.runtime.rules(), invocation.source, counter)?
                > 0);
        }
        Ok(true)
    }

    fn is_active_target(&self, target: EntityRef) -> bool {
        let EntityRef::Character { player, slot } = target else {
            return false;
        };
        self.state.players[player].active == slot
    }

    fn damage_invocations(&self) -> Vec<DamageInvocation> {
        let mut invocations = Vec::new();
        for (player, state) in self.state.players.iter().enumerate() {
            for (slot, character) in state.characters.iter().enumerate() {
                for modifier in &character.modifiers {
                    collect_damage_rule(
                        &self.runtime,
                        player,
                        Some(EntityRef::Character { player, slot }),
                        modifier,
                        &mut invocations,
                    );
                }
            }
            for modifier in state
                .combat
                .iter()
                .chain(&state.summons)
                .chain(&state.supports)
            {
                collect_damage_rule(&self.runtime, player, None, modifier, &mut invocations);
            }
        }
        invocations.sort_by_key(|value| modifier_instance(value.source));
        invocations
    }

    fn apply_reaction_result(
        &mut self,
        context: &RuleContext,
        target: EntityRef,
        reaction: reaction::ReactionMatch,
        defeated: bool,
    ) -> Result<()> {
        if let Some(definition) = reaction.kind.modifier()
            && !(defeated && reaction.kind == Reaction::Frozen)
        {
            let host = if reaction.kind == Reaction::Frozen {
                target
            } else {
                context
                    .source
                    .ok_or_else(|| EngineError::Rule("reaction has no source entity".to_owned()))?
            };
            self.add_modifier(host, definition)?;
        }
        if let Some(element) = reaction.kind.collateral(reaction.aura) {
            self.damage_other_characters(context, target, element)?;
        }
        Ok(())
    }

    fn damage_other_characters(
        &mut self,
        context: &RuleContext,
        target: EntityRef,
        element: Element,
    ) -> Result<()> {
        let EntityRef::Character { player, slot } = target else {
            unreachable!()
        };
        let candidates = self.alive_slots(player)?;
        for other in candidates.into_iter().filter(|other| *other != slot) {
            self.apply_damage(
                context.clone(),
                EntityRef::Character {
                    player,
                    slot: other,
                },
                element,
                1,
            )?;
        }
        Ok(())
    }

    fn handle_defeat(&mut self, target: EntityRef, force_switch: bool) -> Result<()> {
        let EntityRef::Character { player, slot } = target else {
            unreachable!()
        };
        let character = self.state.character_mut(player, slot)?;
        character.auras.clear();
        character.modifiers.clear();
        let alive = self.alive_slots(player)?;
        if alive.is_empty() {
            self.finish_match(1 - player, crate::FinishReason::Defeat);
        } else if self.state.players[player].active == slot {
            if force_switch {
                self.switch_next(player)?;
            } else {
                self.create_switch_decision(player, alive);
            }
        }
        Ok(())
    }

    fn create_switch_decision(&mut self, player: PlayerId, alive: Vec<usize>) {
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

    fn switch_next(&mut self, player: PlayerId) -> Result<()> {
        let Some(slot) = self.next_alive_slot(player)? else {
            return Ok(());
        };
        self.force_switch(
            player,
            ChoiceOption {
                id: slot.to_string(),
                label: format!("character:{slot}"),
            },
        )
    }

    fn next_alive_slot(&self, player: PlayerId) -> Result<Option<usize>> {
        let current = self.state.players[player].active;
        let count = self.state.players[player].characters.len();
        for offset in 1..count {
            let slot = (current + offset) % count;
            if self.is_alive(EntityRef::Character { player, slot })? {
                return Ok(Some(slot));
            }
        }
        Ok(None)
    }

    fn create_choice(
        &mut self,
        options: Vec<ChoiceOption>,
        continuation: &str,
        context: RuleContext,
    ) -> Result<()> {
        if options.is_empty() {
            return Err(EngineError::Rule("choice has no options".to_owned()));
        }
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
        let player = context
            .actor
            .ok_or_else(|| EngineError::Rule("choice requires an acting character".to_owned()))?
            .player();
        self.state.decision = Some(Decision {
            id: self.state.next_decision,
            player,
            options,
        });
        self.state.next_decision += 1;
        self.pending = Some(PendingDecision::Continuation { handler, context });
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
        if self.merge_existing_modifier(player, host, &definition)? {
            return Ok(());
        }
        self.replace_equipment(player, host, &definition)?;
        if modifier_zone_full(&self.state, player, definition.zone) {
            return self.create_modifier_replacement(target, &definition);
        }
        self.insert_modifier(player, host, &definition)
    }

    fn merge_existing_modifier(
        &mut self,
        player: PlayerId,
        host: usize,
        definition: &crate::ModifierDefinition,
    ) -> Result<bool> {
        if definition.merge == MergePolicy::Independent {
            return Ok(false);
        }
        let modifiers = self
            .state
            .modifier_list_mut(player, definition.zone, host)?;
        let Some(existing) = modifiers
            .iter_mut()
            .find(|modifier| modifier.definition == definition.id)
        else {
            return Ok(false);
        };
        merge_modifier(existing, definition);
        Ok(true)
    }

    fn replace_equipment(
        &mut self,
        player: PlayerId,
        host: usize,
        definition: &crate::ModifierDefinition,
    ) -> Result<()> {
        let Some(instance) = definition
            .slot
            .as_deref()
            .and_then(|slot| self.equipped_instance(player, host, slot))
        else {
            return Ok(());
        };
        self.remove_modifier(EntityRef::Modifier { player, instance })
    }

    fn insert_modifier(
        &mut self,
        player: PlayerId,
        host: usize,
        definition: &crate::ModifierDefinition,
    ) -> Result<()> {
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
            reaction: None,
            amount: 0,
        })
    }

    fn equipped_instance(&self, player: PlayerId, host: usize, slot: &str) -> Option<u32> {
        self.state.players[player].characters[host]
            .modifiers
            .iter()
            .find(|modifier| {
                self.runtime
                    .rules()
                    .modifier(&modifier.definition)
                    .is_some_and(|definition| definition.slot.as_deref() == Some(slot))
            })
            .map(|modifier| modifier.instance)
    }

    fn create_modifier_replacement(
        &mut self,
        target: EntityRef,
        definition: &crate::ModifierDefinition,
    ) -> Result<()> {
        let player = target.player();
        let modifiers = self.state.modifier_list_mut(player, definition.zone, 0)?;
        let options = modifiers
            .iter()
            .map(|modifier| ChoiceOption {
                id: modifier.instance.to_string(),
                label: self
                    .runtime
                    .rules()
                    .modifier(&modifier.definition)
                    .expect("state references a loaded modifier")
                    .name
                    .clone(),
            })
            .collect();
        self.state.decision = Some(Decision {
            id: self.state.next_decision,
            player,
            options,
        });
        self.state.next_decision += 1;
        self.pending = Some(PendingDecision::ModifierReplacement {
            target,
            definition: definition.id.clone(),
        });
        Ok(())
    }

    fn replace_modifier(
        &mut self,
        player: PlayerId,
        selected: ChoiceOption,
        target: EntityRef,
        definition: &str,
    ) -> Result<()> {
        let instance = selected.id.parse::<u32>().map_err(|error| {
            EngineError::Rule(format!("invalid modifier replacement option: {error}"))
        })?;
        self.remove_modifier(EntityRef::Modifier { player, instance })?;
        self.add_modifier(target, definition)
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
            reaction: None,
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
        self.state.history.push(event.clone());
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
                    option: None,
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

fn context_owner(context: &RuleContext) -> Result<PlayerId> {
    context
        .source
        .or(context.actor)
        .map(EntityRef::player)
        .ok_or_else(|| EngineError::Rule("effect context has no owner".to_owned()))
}

fn switch_action() -> ActionDefinition {
    ActionDefinition {
        id: "switch".to_owned(),
        name: "Switch".to_owned(),
        tempo: ActionTempo::Combat,
        cost: crate::Cost {
            any: 1,
            ..crate::Cost::default()
        },
        resolve: 0,
        continuations: Default::default(),
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

fn modifier_zone_full(state: &GameState, player: PlayerId, zone: Zone) -> bool {
    match zone {
        Zone::Summon => state.players[player].summons.len() >= 4,
        Zone::Support => state.players[player].supports.len() >= 4,
        Zone::Character | Zone::Combat => false,
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

fn damage_owner_matches(
    direction: DamageDirection,
    owner: PlayerId,
    source: Option<EntityRef>,
    target: EntityRef,
) -> bool {
    match direction {
        DamageDirection::Outgoing => source.is_some_and(|value| value.player() == owner),
        DamageDirection::Incoming => target.player() == owner,
    }
}

fn damage_element_matches(rule: &DamageModifierDefinition, element: Element) -> bool {
    if element == Element::Piercing && !rule.include_piercing {
        return false;
    }
    rule.elements.is_empty() || rule.elements.contains(&element)
}

fn damage_host_matches(
    host: Option<EntityRef>,
    direction: DamageDirection,
    actor: Option<EntityRef>,
    target: EntityRef,
) -> bool {
    let Some(host) = host else {
        return true;
    };
    match direction {
        DamageDirection::Outgoing => actor == Some(host),
        DamageDirection::Incoming => target == host,
    }
}

fn apply_action_rule(action: &mut ActionDefinition, rule: &ActionModifierDefinition) -> bool {
    let reduced = action.cost.reduce_dice(rule.reduce_dice) > 0;
    let tempo_changed = rule.tempo.is_some_and(|tempo| tempo != action.tempo);
    if let Some(tempo) = rule.tempo {
        action.tempo = tempo;
    }
    reduced || tempo_changed
}

fn modifier_instance(source: EntityRef) -> u32 {
    let EntityRef::Modifier { instance, .. } = source else {
        unreachable!()
    };
    instance
}

fn character_slot(character: EntityRef) -> usize {
    let EntityRef::Character { slot, .. } = character else {
        unreachable!()
    };
    slot
}

fn collect_damage_rule(
    runtime: &LuaRuntime,
    player: PlayerId,
    host: Option<EntityRef>,
    modifier: &ModifierState,
    output: &mut Vec<DamageInvocation>,
) {
    let definition = runtime
        .rules()
        .modifier(&modifier.definition)
        .expect("state references a loaded modifier");
    let Some(rule) = definition.damage.clone() else {
        return;
    };
    output.push(DamageInvocation {
        source: EntityRef::Modifier {
            player,
            instance: modifier.instance,
        },
        host,
        rule,
    });
}

fn collect_action_rule(
    runtime: &LuaRuntime,
    player: PlayerId,
    host: Option<EntityRef>,
    modifier: &ModifierState,
    output: &mut Vec<ActionInvocation>,
) {
    let definition = runtime
        .rules()
        .modifier(&modifier.definition)
        .expect("state references a loaded modifier");
    let Some(rule) = definition.action.clone() else {
        return;
    };
    output.push(ActionInvocation {
        source: EntityRef::Modifier {
            player,
            instance: modifier.instance,
        },
        host,
        rule,
    });
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
