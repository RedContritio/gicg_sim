use std::rc::Rc;

use gicg_engine::{Command, DiceSet, Die, EntityRef, Game, GameConfig, LuaRuntime, PlayerConfig};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

#[test]
fn cards_select_healing_targets_and_draw_from_the_deck() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = |card: &str| PlayerConfig {
        characters: vec!["kaeya".to_owned(), "kaeya".to_owned()],
        deck: vec![card.to_owned(); 15],
        active: 0,
        dice: omni(32),
    };
    let mut game = Game::new(
        Rc::clone(&runtime),
        GameConfig {
            players: [player("strategize"), player("sweet_madame")],
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

    game.submit(Command::Skill {
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    let decision = game.state.decision.as_ref().unwrap();
    assert_eq!(decision.options.len(), 2);
    game.choose(decision.id, 0).unwrap();
    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Character { player: 1, slot: 0 },
                "hp"
            )
            .unwrap(),
        8
    );

    game.submit(Command::End).unwrap();
    game.submit(Command::Card {
        hand: 0,
        payment: omni(1),
    })
    .unwrap();
    assert_eq!(game.state.players[0].hand.len(), 6);
    assert_eq!(game.state.players[0].deck.len(), 8);
    assert_eq!(game.state.players[0].discard.len(), 1);
}
