use std::rc::Rc;

use gicg_engine::{
    Command, DiceSet, Die, EntityRef, Game, GameConfig, LuaRuntime, Phase, PlayerConfig,
};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

fn first_die(dice: DiceSet) -> DiceSet {
    let mut payment = DiceSet::default();
    let die = Die::ALL.into_iter().find(|die| dice.get(*die) > 0).unwrap();
    payment.set(die, 1);
    payment
}

#[test]
fn kaeya_skills_and_icicle_follow_real_results() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = PlayerConfig {
        characters: vec!["kaeya".to_owned(), "kaeya".to_owned()],
        deck: vec!["splash".to_owned(); 15],
        active: 0,
        dice: omni(16),
    };
    let mut game = Game::new(
        Rc::clone(&runtime),
        GameConfig {
            players: [player.clone(), player],
            first: 0,
            seed: 7,
        },
    )
    .unwrap();

    game.submit(Command::Redraw {
        selected: Vec::new(),
    })
    .unwrap();
    game.submit(Command::Redraw {
        selected: Vec::new(),
    })
    .unwrap();
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();

    game.submit(Command::Skill {
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Character { player: 1, slot: 0 },
                "hp"
            )
            .unwrap(),
        7
    );
    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Character { player: 0, slot: 0 },
                "energy"
            )
            .unwrap(),
        1
    );

    game.submit(Command::Skill {
        action: "ceremonial_bladework".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::Skill {
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::Skill {
        action: "glacial_waltz".to_owned(),
        payment: omni(4),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 0,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();

    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Character { player: 1, slot: 0 },
                "hp"
            )
            .unwrap(),
        2
    );
    assert_eq!(game.state.players[0].combat.len(), 1);
    let icicle = &game.state.players[0].combat[0];
    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Modifier {
                    player: 0,
                    instance: icicle.instance,
                },
                "uses",
            )
            .unwrap(),
        2
    );
}

#[test]
fn opening_cards_and_round_transition_follow_match_flow() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = PlayerConfig {
        characters: vec!["kaeya".to_owned()],
        deck: vec!["splash".to_owned(); 15],
        active: 0,
        dice: DiceSet::default(),
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

    game.submit(Command::Redraw {
        selected: vec![0, 1],
    })
    .unwrap();
    game.submit(Command::Redraw {
        selected: Vec::new(),
    })
    .unwrap();
    assert_eq!(game.state.phase, Phase::Roll);
    assert_eq!(game.state.players[0].hand.len(), 5);
    assert_eq!(game.state.players[0].dice.total(), 8);

    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.phase, Phase::Action);

    game.submit(Command::Card {
        hand: 0,
        payment: first_die(game.state.players[0].dice),
    })
    .unwrap();
    assert_eq!(game.state.turn, 0);
    assert_eq!(game.state.players[0].discard.len(), 1);

    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert_eq!(game.state.round, 2);
    assert_eq!(game.state.phase, Phase::Roll);
    assert_eq!(game.state.turn, 0);
    assert_eq!(game.state.players[0].hand.len(), 6);
    assert_eq!(game.state.players[1].hand.len(), 7);
    assert_eq!(game.state.players[0].dice.total(), 8);
    assert_eq!(game.state.players[1].dice.total(), 8);
}
