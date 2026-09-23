use std::{path::PathBuf, rc::Rc};

use gicg_engine::{
    Command, DiceSet, Game, GameConfig, GameState, LuaRuntime, MatchFormat, PlayerActionPreviews,
    PlayerConfig,
};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use serde::Serialize;

#[derive(Serialize)]
struct Snapshot<'a> {
    #[serde(flatten)]
    state: &'a GameState,
    action_previews: [PlayerActionPreviews; 2],
}

#[pyclass(unsendable)]
struct GameSession {
    game: Game,
}

#[pymethods]
impl GameSession {
    #[new]
    #[pyo3(signature = (
        ruleset,
        player_one,
        player_two,
        decks,
        format,
        seed=1,
        first=0
    ))]
    fn new(
        ruleset: PathBuf,
        player_one: Vec<String>,
        player_two: Vec<String>,
        decks: (Vec<String>, Vec<String>),
        format: (usize, usize, usize),
        seed: u64,
        first: usize,
    ) -> PyResult<Self> {
        let runtime = Rc::new(LuaRuntime::load(ruleset).map_err(runtime_error)?);
        let player = |characters, deck| PlayerConfig {
            characters,
            deck,
            active: None,
            dice: DiceSet::default(),
        };
        let game = Game::new_match(
            runtime,
            GameConfig {
                players: [player(player_one, decks.0), player(player_two, decks.1)],
                first,
                seed,
            },
            MatchFormat {
                characters: format.0,
                cards: format.1,
                max_card_copies: format.2,
            },
        )
        .map_err(runtime_error)?;
        Ok(Self { game })
    }

    fn snapshot_json(&self) -> PyResult<String> {
        let action_previews = self.game.action_previews().map_err(runtime_error)?;
        serde_json::to_string(&Snapshot {
            state: &self.game.state,
            action_previews,
        })
        .map_err(runtime_error)
    }

    fn rules_json(&self) -> PyResult<String> {
        serde_json::to_string(self.game.rules()).map_err(runtime_error)
    }

    fn legal_actions_json(&self) -> PyResult<String> {
        let actions = if let Some(decision) = &self.game.state.decision {
            decision
                .options
                .iter()
                .enumerate()
                .map(|(option, _)| {
                    serde_json::json!({
                        "kind": "choose",
                        "decision": decision.id,
                        "option": option,
                    })
                })
                .collect()
        } else {
            self.game
                .legal_commands()
                .map_err(runtime_error)?
                .into_iter()
                .map(serde_json::to_value)
                .collect::<Result<Vec<_>, _>>()
                .map_err(runtime_error)?
        };
        serde_json::to_string(&actions).map_err(runtime_error)
    }

    fn submit(&mut self, command: &str) -> PyResult<String> {
        let command = serde_json::from_str::<Command>(command)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        self.game.submit(command).map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn choose(&mut self, decision: u64, option: usize) -> PyResult<String> {
        self.game.choose(decision, option).map_err(runtime_error)?;
        self.snapshot_json()
    }

    fn act(&mut self, action: &str) -> PyResult<String> {
        let value = serde_json::from_str::<serde_json::Value>(action)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        if value.get("kind").and_then(serde_json::Value::as_str) == Some("choose") {
            let decision = value
                .get("decision")
                .and_then(serde_json::Value::as_u64)
                .ok_or_else(|| PyValueError::new_err("choice is missing decision"))?;
            let option = value
                .get("option")
                .and_then(serde_json::Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
                .ok_or_else(|| PyValueError::new_err("choice is missing option"))?;
            self.game.choose(decision, option).map_err(runtime_error)?;
        } else {
            let command = serde_json::from_value::<Command>(value)
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
            self.game.submit(command).map_err(runtime_error)?;
        }
        self.snapshot_json()
    }
}

fn runtime_error(error: impl ToString) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GameSession>()?;
    Ok(())
}
