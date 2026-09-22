use std::{path::PathBuf, rc::Rc};

use gicg_engine::{
    ActionDefinition, ActionTempo, CharacterState, Command, CounterSchema, DiceSet, Die, Game,
    GameConfig, LuaRuntime, ModifierState, Phase, PlayerConfig, Zone,
};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use serde::Serialize;

#[derive(Serialize)]
struct Snapshot {
    ruleset: String,
    round: u16,
    phase: &'static str,
    turn: u8,
    winner: Option<u8>,
    decision: Option<DecisionView>,
    players: Vec<PlayerView>,
}

#[derive(Serialize)]
struct DecisionView {
    id: u64,
    kind: &'static str,
    player: u8,
    options: Vec<OptionView>,
}

#[derive(Serialize)]
struct OptionView {
    id: String,
    label: String,
}

#[derive(Serialize)]
struct PlayerView {
    id: u8,
    active: u8,
    dice: [u8; Die::COUNT],
    ended: bool,
    deck_count: usize,
    discard_count: usize,
    hand: Vec<CardView>,
    characters: Vec<CharacterView>,
    combat: Vec<ModifierView>,
    summons: Vec<ModifierView>,
    supports: Vec<ModifierView>,
}

#[derive(Serialize)]
struct CardView {
    hand: usize,
    id: String,
    name: String,
    description: String,
    tempo: &'static str,
    cost: CostView,
}

#[derive(Serialize)]
struct CharacterView {
    slot: u8,
    id: String,
    name: String,
    element: String,
    counters: Vec<CounterView>,
    actions: Vec<ActionView>,
    modifiers: Vec<ModifierView>,
}

#[derive(Serialize)]
struct ActionView {
    id: String,
    name: String,
    tempo: &'static str,
    cost: CostView,
}

#[derive(Serialize)]
struct CostView {
    dice: [u8; Die::COUNT],
    any: u8,
    counters: Vec<CounterCostView>,
}

#[derive(Serialize)]
struct CounterCostView {
    name: String,
    require: i32,
}

#[derive(Serialize)]
struct ModifierView {
    instance: u32,
    id: String,
    name: String,
    zone: &'static str,
    counters: Vec<CounterView>,
}

#[derive(Serialize)]
struct CounterView {
    name: String,
    value: i32,
    min: i32,
    max: i32,
}

#[pyclass(unsendable)]
struct GameSession {
    game: Game,
}

#[pymethods]
impl GameSession {
    #[new]
    #[pyo3(signature = (ruleset, player_one, player_two, deck, seed=1, first=0))]
    fn new(
        ruleset: PathBuf,
        player_one: Vec<String>,
        player_two: Vec<String>,
        deck: Vec<String>,
        seed: u64,
        first: u8,
    ) -> PyResult<Self> {
        let runtime = Rc::new(LuaRuntime::load(ruleset).map_err(runtime_error)?);
        let player = |characters| PlayerConfig {
            characters,
            deck: deck.clone(),
            active: 0,
            dice: DiceSet::default(),
        };
        let game = Game::new(
            runtime,
            GameConfig {
                players: [player(player_one), player(player_two)],
                first,
                seed,
            },
        )
        .map_err(runtime_error)?;
        Ok(Self { game })
    }

    fn snapshot_json(&self) -> PyResult<String> {
        serde_json::to_string(&self.snapshot()).map_err(runtime_error)
    }

    fn action(&mut self, action: String, payment: Vec<u8>) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::CharacterAction {
                player,
                action,
                payment: dice(payment)?,
            })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn switch(&mut self, slot: u8, payment: Vec<u8>) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::Switch {
                player,
                slot,
                payment: dice(payment)?,
            })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn play_card(&mut self, hand: usize, payment: Vec<u8>) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::PlayCard {
                player,
                hand,
                payment: dice(payment)?,
            })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn redraw(&mut self, hand: Vec<usize>) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::Redraw { player, hand })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn reroll(&mut self, selected: Vec<u8>) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::Reroll {
                player,
                dice: dice(selected)?,
            })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn tune(&mut self, hand: usize, die: usize) -> PyResult<String> {
        let player = self.game.state.turn;
        let die = Die::ALL
            .get(die)
            .copied()
            .ok_or_else(|| PyValueError::new_err("die index must be between 0 and 7"))?;
        self.game
            .submit(Command::Tune { player, hand, die })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn end_round(&mut self) -> PyResult<String> {
        let player = self.game.state.turn;
        self.game
            .submit(Command::EndRound { player })
            .map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn choose(&mut self, decision: u64, option: usize) -> PyResult<String> {
        self.game.choose(decision, option).map_err(runtime_error)?;
        self.snapshot_json()
    }
}

impl GameSession {
    fn snapshot(&self) -> Snapshot {
        let rules = self.game.rules();
        let state = &self.game.state;
        let players = state
            .players
            .iter()
            .enumerate()
            .map(|(player, value)| PlayerView {
                id: player as u8,
                active: value.active,
                dice: value.dice.0,
                ended: value.ended,
                deck_count: value.deck.len(),
                discard_count: value.discard.len(),
                hand: value
                    .hand
                    .iter()
                    .enumerate()
                    .map(|(hand, definition)| {
                        let card = rules
                            .card_definition(*definition)
                            .expect("loaded card definition exists");
                        CardView {
                            hand,
                            id: card.id.clone(),
                            name: card.name.clone(),
                            description: card.description.clone(),
                            tempo: tempo(card.action.tempo),
                            cost: cost_view(&card.action, None),
                        }
                    })
                    .collect(),
                characters: value
                    .characters
                    .iter()
                    .enumerate()
                    .map(|(slot, character)| character_view(rules, character, slot as u8))
                    .collect(),
                combat: modifier_views(rules, &value.combat),
                summons: modifier_views(rules, &value.summons),
                supports: modifier_views(rules, &value.supports),
            })
            .collect();
        Snapshot {
            ruleset: rules.hash.clone(),
            round: state.round,
            phase: match state.phase {
                Phase::Redraw => "redraw",
                Phase::Roll => "roll",
                Phase::Action => "action",
                Phase::Finished => "finished",
            },
            turn: state.turn,
            winner: state.winner,
            decision: state.decision.as_ref().map(|decision| DecisionView {
                id: decision.id,
                kind: match decision.kind {
                    gicg_engine::DecisionKind::Choice => "choice",
                    gicg_engine::DecisionKind::ForcedSwitch => "forced_switch",
                },
                player: decision.player,
                options: decision
                    .options
                    .iter()
                    .map(|option| OptionView {
                        id: option.id.clone(),
                        label: option.label.clone(),
                    })
                    .collect(),
            }),
            players,
        }
    }
}

fn character_view(rules: &gicg_engine::Ruleset, state: &CharacterState, slot: u8) -> CharacterView {
    let definition = rules
        .character_definition(state.definition)
        .expect("loaded character definition exists");
    CharacterView {
        slot,
        id: definition.id.clone(),
        name: definition.name.clone(),
        element: definition.element.to_string(),
        counters: counters(&definition.counters, &state.counters),
        actions: definition
            .actions
            .iter()
            .map(|action| action_view(action, &definition.counters))
            .collect(),
        modifiers: modifier_views(rules, &state.modifiers),
    }
}

fn action_view(action: &ActionDefinition, counters: &CounterSchema) -> ActionView {
    ActionView {
        id: action.id.clone(),
        name: action.name.clone(),
        tempo: tempo(action.tempo),
        cost: cost_view(action, Some(counters)),
    }
}

fn cost_view(action: &ActionDefinition, counters: Option<&CounterSchema>) -> CostView {
    CostView {
        dice: action.cost.dice.0,
        any: action.cost.any,
        counters: action
            .cost
            .counters
            .iter()
            .map(|cost| CounterCostView {
                name: counters
                    .and_then(|schema| schema.definition(cost.field))
                    .expect("counter cost belongs to action owner")
                    .name
                    .clone(),
                require: cost.require,
            })
            .collect(),
    }
}

fn tempo(value: ActionTempo) -> &'static str {
    match value {
        ActionTempo::Combat => "combat",
        ActionTempo::Fast => "fast",
    }
}

fn modifier_views(rules: &gicg_engine::Ruleset, values: &[ModifierState]) -> Vec<ModifierView> {
    values
        .iter()
        .map(|state| {
            let definition = rules
                .modifier_definition(state.definition)
                .expect("loaded modifier definition exists");
            ModifierView {
                instance: state.instance,
                id: definition.id.clone(),
                name: definition.name.clone(),
                zone: match definition.zone {
                    Zone::Character => "character",
                    Zone::Combat => "combat",
                    Zone::Summon => "summon",
                    Zone::Support => "support",
                },
                counters: counters(&definition.counters, &state.counters),
            }
        })
        .collect()
}

fn counters(schema: &CounterSchema, values: &[i32]) -> Vec<CounterView> {
    schema
        .fields()
        .iter()
        .zip(values)
        .map(|(definition, value)| CounterView {
            name: definition.name.clone(),
            value: *value,
            min: definition.min,
            max: definition.max,
        })
        .collect()
}

fn dice(values: Vec<u8>) -> PyResult<DiceSet> {
    let values: [u8; Die::COUNT] = values.try_into().map_err(|values: Vec<u8>| {
        PyValueError::new_err(format!(
            "payment has {} dice fields, expected 8",
            values.len()
        ))
    })?;
    Ok(DiceSet(values))
}

fn runtime_error(error: impl ToString) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GameSession>()?;
    Ok(())
}
