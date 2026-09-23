use std::collections::HashMap;

use rand::{SeedableRng, seq::IndexedRandom};
use rand_chacha::ChaCha8Rng;

use crate::{Command, DiceSet, Die, EngineError, EntityRef, Game, GameSignals, Phase, Result};

const HEURISTIC_BRANCH_LIMIT: usize = 8;

#[derive(Clone)]
enum SearchInput {
    Choose {
        index: usize,
        decision: u64,
        option: usize,
    },
    Command {
        index: usize,
        command: Command,
    },
}

impl SearchInput {
    fn index(&self) -> usize {
        match self {
            Self::Choose { index, .. } | Self::Command { index, .. } => *index,
        }
    }

    fn apply(self, game: &mut Game) -> Result<()> {
        match self {
            Self::Choose {
                decision, option, ..
            } => game.choose(decision, option),
            Self::Command { command, .. } => game.submit(command),
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum LogicalAction {
    Skill(String),
    Switch(usize),
    Card(usize),
}

#[derive(Clone, Copy)]
struct ScoreRoot {
    hp: [i32; 2],
    alive: [i32; 2],
    signals: GameSignals,
}

impl ScoreRoot {
    fn new(game: &Game) -> Result<Self> {
        let (hp, alive) = hp_and_alive(game)?;
        Ok(Self {
            hp,
            alive,
            signals: game.signals(),
        })
    }
}

struct SearchBudget(Option<usize>);

impl SearchBudget {
    fn take(&mut self) -> bool {
        let Some(remaining) = &mut self.0 else {
            return true;
        };
        if *remaining == 0 {
            return false;
        }
        *remaining -= 1;
        true
    }

    fn exhausted(&self) -> bool {
        self.0 == Some(0)
    }
}

impl Game {
    pub fn select_greedy_action(
        &self,
        features: u8,
        depth: usize,
        node_budget: usize,
        seed: u64,
    ) -> Result<usize> {
        validate_config(features, depth)?;
        let root = ScoreRoot::new(self)?;
        let me = controller(self);
        let inputs = candidate_inputs(self)?;
        if inputs.is_empty() {
            return Err(EngineError::InvalidCommand(
                "greedy search requires at least one legal action".to_owned(),
            ));
        }
        let mut budget = SearchBudget((node_budget > 0).then_some(node_budget));
        let mut scored = Vec::new();
        for input in inputs {
            if !budget.take() {
                break;
            }
            let mut next = self.clone();
            input.clone().apply(&mut next)?;
            let score = minimax(&next, root, me, features, depth - 1, &mut budget)?;
            scored.push((input.index(), score));
        }
        choose_best(scored, seed)
    }
}

fn validate_config(features: u8, depth: usize) -> Result<()> {
    if !(1..=5).contains(&features) {
        return Err(EngineError::InvalidCommand(format!(
            "greedy features must be in 1..=5, got {features}"
        )));
    }
    if depth == 0 {
        return Err(EngineError::InvalidCommand(
            "greedy depth must be positive".to_owned(),
        ));
    }
    Ok(())
}

fn minimax(
    game: &Game,
    root: ScoreRoot,
    me: usize,
    features: u8,
    depth: usize,
    budget: &mut SearchBudget,
) -> Result<f64> {
    if search_finished(game, depth, budget) {
        return score(game, root, me, features);
    }
    let maximize = controller(game) == me;
    let mut children = ordered_children(game, root, me, features, maximize, budget)?;
    if depth >= 2 {
        children.truncate(HEURISTIC_BRANCH_LIMIT);
    }
    let mut best: Option<f64> = None;
    for (next, _) in children {
        let value = minimax(&next, root, me, features, depth - 1, budget)?;
        best = Some(select_score(best, value, maximize));
    }
    best.map_or_else(|| score(game, root, me, features), Ok)
}

fn ordered_children(
    game: &Game,
    root: ScoreRoot,
    me: usize,
    features: u8,
    maximize: bool,
    budget: &mut SearchBudget,
) -> Result<Vec<(Game, f64)>> {
    let mut children = Vec::new();
    for input in candidate_inputs(game)? {
        if !budget.take() {
            break;
        }
        let mut next = game.clone();
        input.apply(&mut next)?;
        let heuristic = score(&next, root, me, features)?;
        children.push((next, heuristic));
    }
    children.sort_by(|left, right| {
        if maximize {
            right.1.total_cmp(&left.1)
        } else {
            left.1.total_cmp(&right.1)
        }
    });
    Ok(children)
}

fn search_finished(game: &Game, depth: usize, budget: &SearchBudget) -> bool {
    game.state.phase == Phase::Finished || depth == 0 || budget.exhausted()
}

fn select_score(best: Option<f64>, value: f64, maximize: bool) -> f64 {
    match (best, maximize) {
        (None, _) => value,
        (Some(current), true) => current.max(value),
        (Some(current), false) => current.min(value),
    }
}

fn choose_best(scored: Vec<(usize, f64)>, seed: u64) -> Result<usize> {
    let best = scored
        .iter()
        .map(|(_, score)| *score)
        .reduce(f64::max)
        .ok_or_else(|| EngineError::Rule("greedy search exhausted its node budget".to_owned()))?;
    let tied = scored
        .into_iter()
        .filter_map(|(index, score)| (score == best).then_some(index))
        .collect::<Vec<_>>();
    tied.choose(&mut ChaCha8Rng::seed_from_u64(seed))
        .copied()
        .ok_or_else(|| EngineError::Rule("greedy search produced no best action".to_owned()))
}

fn controller(game: &Game) -> usize {
    game.state
        .decision
        .as_ref()
        .map_or(game.state.turn, |decision| decision.player)
}

fn candidate_inputs(game: &Game) -> Result<Vec<SearchInput>> {
    if let Some(decision) = &game.state.decision {
        return Ok((0..decision.options.len())
            .map(|option| SearchInput::Choose {
                index: option,
                decision: decision.id,
                option,
            })
            .collect());
    }
    let commands = game.legal_commands()?;
    if game.state.phase == Phase::Roll {
        return Ok(select_reroll(game, commands));
    }
    Ok(collapse_payments(game, commands))
}

fn select_reroll(game: &Game, commands: Vec<Command>) -> Vec<SearchInput> {
    let player = controller(game);
    let inventory = game.state.players[player].dice;
    let values = die_values(game, player);
    let total = values.iter().sum::<i32>();
    let mut selected = DiceSet::default();
    for die in Die::ALL {
        if total > 8 * values[die.index()] {
            selected.set(die, inventory.get(die));
        }
    }
    commands
        .into_iter()
        .enumerate()
        .find_map(|(index, command)| match command {
            Command::Reroll { payment } if payment == selected => {
                Some(SearchInput::Command { index, command })
            }
            _ => None,
        })
        .into_iter()
        .collect()
}

fn collapse_payments(game: &Game, commands: Vec<Command>) -> Vec<SearchInput> {
    let player = controller(game);
    let values = die_values(game, player);
    let mut positions = HashMap::new();
    let mut selected: Vec<SearchInput> = Vec::new();
    for (index, command) in commands.into_iter().enumerate() {
        let Some((key, payment)) = logical_payment(&command) else {
            selected.push(SearchInput::Command { index, command });
            continue;
        };
        if let Some(position) = positions.get(&key).copied() {
            replace_cheaper(&mut selected[position], index, command, payment, values);
        } else {
            positions.insert(key, selected.len());
            selected.push(SearchInput::Command { index, command });
        }
    }
    selected
}

fn logical_payment(command: &Command) -> Option<(LogicalAction, DiceSet)> {
    match command {
        Command::Skill { action, payment } => {
            Some((LogicalAction::Skill(action.clone()), *payment))
        }
        Command::Switch { slot, payment } => Some((LogicalAction::Switch(*slot), *payment)),
        Command::Card { hand, payment } => Some((LogicalAction::Card(*hand), *payment)),
        _ => None,
    }
}

fn replace_cheaper(
    current: &mut SearchInput,
    index: usize,
    command: Command,
    payment: DiceSet,
    values: [i32; Die::COUNT],
) {
    let SearchInput::Command {
        command: existing, ..
    } = current
    else {
        unreachable!()
    };
    let (_, existing_payment) = logical_payment(existing).expect("grouped action has a payment");
    if payment_cost(payment, values) < payment_cost(existing_payment, values) {
        *current = SearchInput::Command { index, command };
    }
}

fn payment_cost(payment: DiceSet, values: [i32; Die::COUNT]) -> i32 {
    Die::ALL
        .into_iter()
        .map(|die| i32::from(payment.get(die)) * values[die.index()])
        .sum()
}

fn die_values(game: &Game, player: usize) -> [i32; Die::COUNT] {
    let state = &game.state.players[player];
    let mut values = state.dice.0.map(|count| 10 * i32::from(count));
    for (slot, character) in state.characters.iter().enumerate() {
        let target = EntityRef::Character { player, slot };
        if game.state.counter(game.rules(), target, "hp").unwrap_or(0) <= 0 {
            continue;
        }
        let element = game
            .rules()
            .character(&character.definition)
            .expect("state references a loaded character")
            .element;
        let Some(die) = element.die() else {
            continue;
        };
        let tier = if slot == state.active { 1000 } else { 100 };
        values[die.index()] = values[die.index()].max(tier);
    }
    values[Die::Omni.index()] = values[Die::Omni.index()].max(500);
    values
}

fn hp_and_alive(game: &Game) -> Result<([i32; 2], [i32; 2])> {
    let mut hp = [0; 2];
    let mut alive = [0; 2];
    for player in 0..2 {
        for slot in 0..game.state.players[player].characters.len() {
            let value =
                game.state
                    .counter(game.rules(), EntityRef::Character { player, slot }, "hp")?;
            hp[player] += value;
            alive[player] += i32::from(value > 0);
        }
    }
    Ok((hp, alive))
}

fn score(game: &Game, root: ScoreRoot, me: usize, features: u8) -> Result<f64> {
    let (hp, alive) = hp_and_alive(game)?;
    let opponent = 1 - me;
    let dealt = root.hp[opponent] - hp[opponent];
    let taken = root.hp[me] - hp[me];
    let mut value = f64::from(dealt) - 1.1 * f64::from(taken);
    if features >= 2 {
        value += 10.0 * f64::from((root.alive[opponent] - alive[opponent]).max(0));
        value -= 8.0 * f64::from((root.alive[me] - alive[me]).max(0));
    }
    let signals = game.signals();
    if features >= 3 {
        value += f64::from(signals.healing[me] - root.signals.healing[me]);
        value -= 0.8 * f64::from(signals.healing[opponent] - root.signals.healing[opponent]);
    }
    if features >= 4 {
        value += feature_four(signals, root.signals, me, opponent);
    }
    if features >= 5 {
        value += feature_five(signals, root.signals, me);
    }
    Ok(value)
}

fn feature_four(current: GameSignals, root: GameSignals, me: usize, opponent: usize) -> f64 {
    let shield = current.shields[me] - root.shields[me];
    let blocked = current.shields[opponent] - root.shields[opponent];
    let reactions = current.reactions[me] - root.reactions[me];
    let received = current.reactions[opponent] - root.reactions[opponent];
    f64::from(shield) - 0.8 * f64::from(blocked) + f64::from(reactions) - 0.8 * f64::from(received)
}

fn feature_five(current: GameSignals, root: GameSignals, me: usize) -> f64 {
    let overflow = current.energy_overflow[me] - root.energy_overflow[me];
    let wasted = current.dice_wasted[me] - root.dice_wasted[me];
    let kills = current.kills[me] - root.kills[me];
    -0.4 * f64::from(overflow) - dice_waste(wasted)
        + (0..kills)
            .map(|index| 5.0 * f64::from(root.kills[me] + index))
            .sum::<f64>()
}

fn dice_waste(value: i32) -> f64 {
    let value = value.max(0);
    0.2 * f64::from(value.min(3))
        + 0.5 * f64::from((value - 3).clamp(0, 3))
        + 0.8 * f64::from((value - 6).clamp(0, 2))
        + f64::from((value - 8).max(0))
}
