use std::rc::Rc;

use gicg_engine::{
    Command, DiceSet, Die, Element, EntityRef, Game, GameConfig, LuaRuntime, PlayerConfig, Reaction,
};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

fn ready(characters: &[&str]) -> (Rc<LuaRuntime>, Game) {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = PlayerConfig {
        characters: characters.iter().map(|value| (*value).to_owned()).collect(),
        deck: Vec::new(),
        active: Some(0),
        dice: omni(64),
    };
    let mut game = Game::new(
        Rc::clone(&runtime),
        GameConfig {
            players: [player.clone(), player],
            first: 0,
            seed: 1,
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

fn use_action(game: &mut Game, action: &str, dice: u8) {
    game.submit(Command::Skill {
        action: action.to_owned(),
        payment: omni(dice),
    })
    .unwrap();
}

fn set_counter(
    game: &mut Game,
    runtime: &LuaRuntime,
    player: usize,
    slot: usize,
    name: &str,
    value: i32,
) {
    let definition = runtime
        .rules()
        .character(&game.state.players[player].characters[slot].definition)
        .unwrap();
    let field = definition.counters.field(name).unwrap();
    game.state.players[player].characters[slot].counters[field] = value;
}

fn hp(game: &Game, runtime: &LuaRuntime, player: usize, slot: usize) -> i32 {
    game.state
        .counter(runtime.rules(), EntityRef::Character { player, slot }, "hp")
        .unwrap()
}

fn modifier_uses(
    game: &Game,
    runtime: &LuaRuntime,
    player: usize,
    definition: &str,
    name: &str,
) -> Option<i32> {
    let modifier = game.state.players[player]
        .characters
        .iter()
        .flat_map(|character| &character.modifiers)
        .chain(&game.state.players[player].combat)
        .chain(&game.state.players[player].summons)
        .find(|modifier| modifier.definition == definition)?;
    game.state
        .counter(
            runtime.rules(),
            EntityRef::Modifier {
                player,
                instance: modifier.instance,
            },
            name,
        )
        .ok()
}

#[test]
fn direct_reactions_apply_bonus_collateral_and_forced_switch() {
    for (character, action, dice, aura, reaction, hp_after) in [
        (
            "mualani",
            "cooling_treatment",
            3,
            Element::Pyro,
            Reaction::Vaporize,
            7,
        ),
        ("kaeya", "frostgnaw", 3, Element::Pyro, Reaction::Melt, 5),
        (
            "yae_miko",
            "spiritfox_sin_eater",
            3,
            Element::Pyro,
            Reaction::Overloaded,
            7,
        ),
        (
            "kaeya",
            "frostgnaw",
            3,
            Element::Electro,
            Reaction::Superconduct,
            6,
        ),
        (
            "mualani",
            "cooling_treatment",
            3,
            Element::Electro,
            Reaction::ElectroCharged,
            8,
        ),
    ] {
        let (runtime, mut game) = ready(&[character, "kaeya", "alhaitham"]);
        game.state.players[1].characters[0].auras.push(aura);
        use_action(&mut game, action, dice);
        assert_eq!(game.state.last_reaction.unwrap().kind, reaction);
        assert_eq!(hp(&game, &runtime, 1, 0), hp_after);
        assert!(game.state.players[1].characters[0].auras.is_empty());
        if matches!(reaction, Reaction::Superconduct | Reaction::ElectroCharged) {
            assert_eq!(hp(&game, &runtime, 1, 1), 9);
            assert_eq!(hp(&game, &runtime, 1, 2), 9);
        }
        if reaction == Reaction::Overloaded {
            assert_eq!(game.state.players[1].active, 1);
        }
    }
}

#[test]
fn reaction_collateral_is_resolved_before_defeat_switch() {
    let (runtime, mut game) = ready(&["kaeya", "yae_miko", "alhaitham"]);
    set_counter(&mut game, &runtime, 1, 0, "hp", 2);
    set_counter(&mut game, &runtime, 1, 1, "hp", 1);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Electro);

    use_action(&mut game, "frostgnaw", 3);

    assert_eq!(hp(&game, &runtime, 1, 0), 0);
    assert_eq!(hp(&game, &runtime, 1, 1), 0);
    assert_eq!(hp(&game, &runtime, 1, 2), 9);
    let decision = game.state.decision.as_ref().unwrap();
    assert_eq!(decision.player, 1);
    assert_eq!(
        decision
            .options
            .iter()
            .map(|option| option.id.as_str())
            .collect::<Vec<_>>(),
        vec!["2"]
    );
    game.choose(decision.id, 0).unwrap();
    assert_eq!(game.state.players[1].active, 2);
}

#[test]
fn reaction_products_affect_later_damage_and_round_end() {
    let (runtime, mut game) = ready(&["alhaitham", "mavuika", "kaeya"]);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Hydro);
    use_action(&mut game, "universality_an_elaboration_on_form", 3);
    assert_eq!(game.state.last_reaction.unwrap().kind, Reaction::Bloom);
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.dendro_core", "uses"),
        Some(1)
    );
    game.submit(Command::End).unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    set_counter(&mut game, &runtime, 0, 1, "fighting_spirit", 3);
    use_action(&mut game, "hour_of_burning_skies", 4);
    assert_eq!(hp(&game, &runtime, 1, 0), 2);
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.dendro_core", "uses"),
        None
    );

    let (runtime, mut game) = ready(&["chiori", "kaeya"]);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Pyro);
    set_counter(&mut game, &runtime, 0, 0, "energy", 2);
    use_action(&mut game, "hiyoku_twin_blades", 3);
    assert_eq!(
        game.state.last_reaction.unwrap().kind,
        Reaction::Crystallize
    );
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.crystallize_shield", "points"),
        Some(1)
    );
    set_counter(&mut game, &runtime, 1, 0, "energy", 2);
    use_action(&mut game, "hiyoku_twin_blades", 3);
    assert_eq!(hp(&game, &runtime, 0, 0), 6);
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.crystallize_shield", "points"),
        None
    );

    let (runtime, mut game) = ready(&["alhaitham", "kaeya"]);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Pyro);
    use_action(&mut game, "universality_an_elaboration_on_form", 3);
    assert_eq!(game.state.last_reaction.unwrap().kind, Reaction::Burning);
    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert_eq!(hp(&game, &runtime, 1, 0), 6);

    let (runtime, mut game) = ready(&["alhaitham", "kaeya"]);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Electro);
    use_action(&mut game, "universality_an_elaboration_on_form", 3);
    assert_eq!(game.state.last_reaction.unwrap().kind, Reaction::Quicken);
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.catalyzing_field", "uses"),
        Some(2)
    );
    game.submit(Command::End).unwrap();
    use_action(&mut game, "universality_an_elaboration_on_form", 3);
    assert_eq!(hp(&game, &runtime, 1, 0), 4);
    assert_eq!(
        modifier_uses(&game, &runtime, 0, "system.catalyzing_field", "uses"),
        Some(1)
    );
}

#[test]
fn frozen_blocks_actions_and_physical_damage_shatters_it() {
    let (runtime, mut game) = ready(&["mualani", "kaeya"]);
    game.state.players[1].characters[0]
        .auras
        .push(Element::Cryo);
    use_action(&mut game, "cooling_treatment", 3);
    assert_eq!(game.state.last_reaction.unwrap().kind, Reaction::Frozen);
    assert_eq!(
        modifier_uses(&game, &runtime, 1, "system.frozen", "uses"),
        Some(1)
    );
    assert!(
        game.action_previews().unwrap()[1]
            .skills
            .iter()
            .all(|action| !action.playable)
    );
    let error = game
        .submit(Command::Skill {
            action: "cooling_treatment".to_owned(),
            payment: omni(3),
        })
        .unwrap_err();
    assert!(error.to_string().contains("frozen"));

    game.submit(Command::End).unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    use_action(&mut game, "ceremonial_bladework", 3);
    assert_eq!(game.state.last_reaction.unwrap().kind, Reaction::Shatter);
    assert_eq!(
        modifier_uses(&game, &runtime, 1, "system.frozen", "uses"),
        None
    );
}
