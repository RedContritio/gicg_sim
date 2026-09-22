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
        deck,
        format,
        seed=1,
        first=0
    ))]
    fn new(
        ruleset: PathBuf,
        player_one: Vec<String>,
        player_two: Vec<String>,
        deck: Vec<String>,
        format: (usize, usize, usize),
        seed: u64,
        first: usize,
    ) -> PyResult<Self> {
        let runtime = Rc::new(LuaRuntime::load(ruleset).map_err(runtime_error)?);
        let player = |characters| PlayerConfig {
            characters,
            deck: deck.clone(),
            active: None,
            dice: DiceSet::default(),
        };
        let game = Game::new_match(
            runtime,
            GameConfig {
                players: [player(player_one), player(player_two)],
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
}

fn runtime_error(error: impl ToString) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GameSession>()?;
    Ok(())
}
