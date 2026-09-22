use std::rc::Rc;

use gicg_engine::{Command, DiceSet, Die, EntityRef, Game, GameConfig, LuaRuntime, PlayerConfig};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

fn ready(characters: &[&str]) -> (Rc<LuaRuntime>, Game) {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = PlayerConfig {
        characters: characters.iter().map(|value| (*value).to_owned()).collect(),
        deck: vec!["splash".to_owned(); 15],
        active: 0,
        dice: omni(64),
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
    for _ in 0..2 {
        game.submit(Command::Redraw { selected: vec![] }).unwrap();
    }
    for _ in 0..2 {
        game.submit(Command::Reroll {
            payment: DiceSet::default(),
        })
        .unwrap();
    }
    (runtime, game)
}

fn skill(game: &mut Game, action: &str, dice: u8) {
    game.submit(Command::Skill {
        action: action.to_owned(),
        payment: omni(dice),
    })
    .unwrap();
}

fn counter(game: &Game, runtime: &LuaRuntime, player: usize, slot: usize, name: &str) -> i32 {
    game.state
        .counter(runtime.rules(), EntityRef::Character { player, slot }, name)
        .unwrap()
}

fn modifier_counter(
    game: &Game,
    runtime: &LuaRuntime,
    player: usize,
    definition: &str,
    name: &str,
) -> i32 {
    let modifier = game.state.players[player]
        .characters
        .iter()
        .flat_map(|character| &character.modifiers)
        .chain(&game.state.players[player].combat)
        .chain(&game.state.players[player].summons)
        .find(|modifier| modifier.definition == definition)
        .unwrap();
    game.state
        .counter(
            runtime.rules(),
            EntityRef::Modifier {
                player,
                instance: modifier.instance,
            },
            name,
        )
        .unwrap()
}

#[test]
fn yae_miko_stacks_consumes_and_releases_summons() {
    let (runtime, mut game) = ready(&["yae_miko", "kaeya"]);
    skill(&mut game, "yakan_evocation_sesshou_sakura", 3);
    game.submit(Command::End).unwrap();
    skill(&mut game, "yakan_evocation_sesshou_sakura", 3);
    assert_eq!(
        modifier_counter(&game, &runtime, 0, "yae_miko.sesshou_sakura", "uses"),
        6
    );
    assert_eq!(
        modifier_counter(&game, &runtime, 0, "yae_miko.sesshou_sakura", "power"),
        1
    );

    skill(&mut game, "spiritfox_sin_eater", 3);
    skill(&mut game, "spiritfox_sin_eater", 3);
    skill(&mut game, "great_secret_art", 3);
    assert!(game.state.players[0].summons.is_empty());
    assert_eq!(
        game.state.players[0].combat[0].definition,
        "yae_miko.tenko_thunderbolts"
    );

    skill(&mut game, "yakan_evocation_sesshou_sakura", 3);
    assert!(game.state.players[0].combat.is_empty());
    assert_eq!(counter(&game, &runtime, 1, 0, "hp"), 1);
}

#[test]
fn alhaitham_mirror_changes_attack_and_burst_duration() {
    let (runtime, mut game) = ready(&["alhaitham", "kaeya"]);
    skill(&mut game, "universality_an_elaboration_on_form", 3);
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    skill(&mut game, "abductive_reasoning", 3);
    game.submit(Command::Switch {
        slot: 0,
        payment: omni(1),
    })
    .unwrap();
    skill(&mut game, "particular_field_fetters_of_phenomena", 3);

    assert_eq!(counter(&game, &runtime, 1, 0, "hp"), 2);
    assert_eq!(
        modifier_counter(
            &game,
            &runtime,
            0,
            "alhaitham.chisel_light_mirror",
            "rounds"
        ),
        1
    );
}

#[test]
fn chiori_all_puppet_choices_enter_and_tick() {
    for (option, definition) in [
        "calm",
        "easy",
        "closed",
        "nothing",
        "side_eye",
        "displeased",
    ]
    .into_iter()
    .enumerate()
    {
        let (runtime, mut game) = ready(&["chiori"]);
        skill(&mut game, "fluttering_hasode", 3);
        let decision = game.state.decision.as_ref().unwrap().id;
        game.choose(decision, option).unwrap();
        assert_eq!(
            game.state.players[0].summons[0].definition,
            format!("chiori.{definition}")
        );
        game.submit(Command::End).unwrap();
        game.submit(Command::End).unwrap();
        assert_eq!(
            modifier_counter(&game, &runtime, 0, &format!("chiori.{definition}"), "uses"),
            1
        );
        assert_eq!(counter(&game, &runtime, 1, 0, "hp"), 9);
    }
}

#[test]
fn full_summon_zone_replaces_the_selected_summon() {
    let (_, mut game) = ready(&["chiori"]);
    skill(&mut game, "fluttering_hasode", 3);
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();
    game.submit(Command::End).unwrap();

    for option in 1..5 {
        skill(&mut game, "fluttering_hasode", 3);
        let decision = game.state.decision.as_ref().unwrap().id;
        game.choose(decision, option).unwrap();
    }
    assert_eq!(game.state.players[0].summons.len(), 4);
    let replacement = game.state.decision.as_ref().unwrap().id;
    game.choose(replacement, 0).unwrap();
    assert_eq!(
        game.state.players[0]
            .summons
            .iter()
            .map(|summon| summon.definition.as_str())
            .collect::<Vec<_>>(),
        [
            "chiori.easy",
            "chiori.closed",
            "chiori.nothing",
            "chiori.side_eye",
        ]
    );
}

#[test]
fn mualani_nightsoul_action_and_missile_complete_the_cycle() {
    let (runtime, mut game) = ready(&["mualani"]);
    skill(&mut game, "surfshark_wavebreaker", 2);
    game.submit(Command::End).unwrap();
    skill(&mut game, "sharky_surfboard", 0);
    skill(&mut game, "cooling_treatment", 3);
    skill(&mut game, "cooling_treatment", 3);
    skill(&mut game, "boomsharka_laka", 3);

    assert_eq!(counter(&game, &runtime, 0, 0, "nightsoul"), 1);
    assert_eq!(counter(&game, &runtime, 0, 0, "bite_stacks"), 1);
    assert_eq!(
        modifier_counter(&game, &runtime, 0, "mualani.shark_missile", "uses"),
        2
    );
    game.submit(Command::End).unwrap();
    assert_eq!(
        modifier_counter(&game, &runtime, 0, "mualani.shark_missile", "uses"),
        1
    );
    assert_eq!(counter(&game, &runtime, 1, 0, "hp"), 4);
}

#[test]
fn mavuika_choices_cross_character_trigger_and_burst_resource() {
    for (option, card) in [
        "mavuika.motorcycle_leap",
        "mavuika.motorcycle_traverse",
        "mavuika.motorcycle_sprint",
    ]
    .into_iter()
    .enumerate()
    {
        let (_, mut game) = ready(&["mavuika", "kaeya"]);
        skill(&mut game, "the_named_moment", 3);
        let decision = game.state.decision.as_ref().unwrap().id;
        game.choose(decision, option).unwrap();
        assert_eq!(game.state.players[0].hand.last().unwrap(), card);
    }

    let (runtime, mut game) = ready(&["mavuika", "kaeya"]);
    skill(&mut game, "the_named_moment", 3);
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::End).unwrap();
    skill(&mut game, "ceremonial_bladework", 3);
    assert_eq!(counter(&game, &runtime, 0, 0, "fighting_spirit"), 1);

    game.submit(Command::Card {
        hand: 5,
        payment: omni(1),
    })
    .unwrap();
    assert_eq!(counter(&game, &runtime, 0, 0, "fighting_spirit"), 3);
    assert!(game.state.players[0].combat.is_empty());
    game.submit(Command::Switch {
        slot: 0,
        payment: omni(1),
    })
    .unwrap();
    skill(&mut game, "hour_of_burning_skies", 4);
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();
    assert_eq!(counter(&game, &runtime, 0, 0, "fighting_spirit"), 0);
    assert_eq!(counter(&game, &runtime, 0, 0, "nightsoul"), 2);
}
