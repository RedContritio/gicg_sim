use std::rc::Rc;

use gicg_engine::{Command, DiceSet, Die, Game, GameConfig, LuaRuntime, PlayerConfig};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

#[test]
fn f1d1_prefers_the_highest_immediate_damage() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = PlayerConfig {
        characters: vec!["kaeya".to_owned(), "yae_miko".to_owned()],
        deck: vec!["splash".to_owned(); 15],
        active: Some(0),
        dice: omni(16),
    };
    let mut game = Game::new(
        runtime,
        GameConfig {
            players: [player.clone(), player],
            first: 0,
            seed: 7,
        },
    )
    .unwrap();
    for _ in 0..2 {
        game.submit(Command::Redraw { selected: vec![] }).unwrap();
    }
    for _ in 0..2 {
        game.submit(Command::Reroll {
            payment: DiceSet::default(),
        })
        .unwrap();
    }

    let index = game.select_greedy_action(1, 1, 10_000, 7).unwrap();
    let command = &game.legal_commands().unwrap()[index];
    assert!(matches!(command, Command::Skill { action, .. } if action == "frostgnaw"));
}
