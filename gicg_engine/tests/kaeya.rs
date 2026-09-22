use gicg_engine::{Command, DiceSet, Die, EntityRef, Game, GameConfig, LuaRuntime, PlayerConfig};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

#[test]
fn kaeya_skills_and_icicle_follow_real_results() {
    let runtime = LuaRuntime::load("../data/native_latest").unwrap();
    let player = PlayerConfig {
        characters: vec!["kaeya".to_owned(), "kaeya".to_owned()],
        active: 0,
        dice: omni(16),
    };
    let mut game = Game::new(
        &runtime,
        GameConfig {
            players: [player.clone(), player],
            first: 0,
        },
    )
    .unwrap();

    game.submit(Command::CharacterAction {
        player: 0,
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

    game.submit(Command::CharacterAction {
        player: 1,
        action: "ceremonial_bladework".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::CharacterAction {
        player: 0,
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::Switch {
        player: 1,
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::CharacterAction {
        player: 0,
        action: "glacial_waltz".to_owned(),
        payment: omni(4),
    })
    .unwrap();
    game.submit(Command::Switch {
        player: 1,
        slot: 0,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::Switch {
        player: 0,
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
