use std::rc::Rc;

use gicg_engine::{
    ActionKind, Command, DiceSet, Die, EntityRef, EventKind, Game, GameConfig, LuaRuntime,
    MatchFormat, PlayerConfig,
};

fn omni(count: u8) -> DiceSet {
    let mut dice = DiceSet::default();
    dice.set(Die::Omni, count);
    dice
}

fn take(dice: DiceSet, count: u8) -> DiceSet {
    let mut payment = DiceSet::default();
    let mut remaining = count;
    for die in Die::ALL {
        let selected = dice.get(die).min(remaining);
        payment.set(die, selected);
        remaining -= selected;
    }
    assert_eq!(remaining, 0);
    payment
}

#[test]
fn cards_select_healing_targets_and_draw_from_the_deck() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = |card: &str| PlayerConfig {
        characters: vec!["kaeya".to_owned(), "yae_miko".to_owned()],
        deck: vec![card.to_owned(); 15],
        active: Some(0),
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
    assert_eq!(decision.options.len(), 1);
    game.choose(decision.id, 0).unwrap();
    assert!(game.state.players[1].characters[0].satiated);
    assert!(!game.action_previews().unwrap()[1].cards[0].playable);
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

    let mut game = ready("sweet_madame");
    assert!(!game.action_previews().unwrap()[0].cards[0].playable);
    assert!(
        game.submit(Command::Card {
            hand: 0,
            payment: DiceSet::default(),
        })
        .is_err()
    );
    assert_eq!(game.state.players[0].hand.len(), 5);
    assert!(game.state.players[0].discard.is_empty());
}

fn ready(card: &str) -> Game {
    ready_with_cards([card, card])
}

fn ready_with_cards(cards: [&str; 2]) -> Game {
    ready_with_dice(cards, omni(32))
}

fn ready_with_dice(cards: [&str; 2], dice: DiceSet) -> Game {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = |card: &str| PlayerConfig {
        characters: vec!["kaeya".to_owned(), "yae_miko".to_owned()],
        deck: vec![card.to_owned(); 15],
        active: Some(0),
        dice,
    };
    let mut game = Game::new(
        runtime,
        GameConfig {
            players: [player(cards[0]), player(cards[1])],
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
    game
}

#[test]
fn draw_and_random_discard_emit_card_events() {
    let mut game = ready_with_cards(["miscalculation", "splash"]);
    assert_eq!(
        game.state
            .history
            .iter()
            .filter(|event| event.kind == gicg_engine::EventKind::CardDrawn)
            .count(),
        10
    );
    game.submit(Command::Card {
        hand: 0,
        payment: omni(1),
    })
    .unwrap();
    assert_eq!(game.state.players[1].hand.len(), 4);
    assert_eq!(game.state.players[1].discard, ["splash"]);
    assert!(
        game.state.history.iter().any(|event| {
            event.kind == gicg_engine::EventKind::CardDiscarded && event.player == 1
        })
    );

    let mut game = ready_with_dice(["mavuika.motorcycle_traverse", "splash"], omni(15));
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.players[0].dice.total(), DiceSet::MAX_TOTAL);
}

#[test]
fn cards_modify_switch_cost_and_tempo() {
    let mut game = ready("leave_it_to_me");
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: omni(1),
    })
    .unwrap();
    assert_eq!(game.state.turn, 0);
    assert!(game.state.players[0].combat.is_empty());
    game.submit(Command::Skill {
        action: "spiritfox_sin_eater".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    let action = game
        .state
        .history
        .iter()
        .rev()
        .find(|event| event.kind == EventKind::ActionResolved)
        .unwrap();
    assert_eq!(action.action_kind, Some(ActionKind::Skill));
    assert!(action.traits.plunging);

    let mut game = ready("changing_shifts");
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    game.submit(Command::Switch {
        slot: 1,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.turn, 1);
    assert!(game.state.players[0].combat.is_empty());

    let mut game = ready("when_the_crane_returned");
    game.submit(Command::Card {
        hand: 0,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::Skill {
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    assert_eq!(game.state.players[0].active, 1);
    assert!(game.state.players[0].combat.is_empty());
    game.submit(Command::End).unwrap();
    game.submit(Command::Skill {
        action: "spiritfox_sin_eater".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    let action = game
        .state
        .history
        .iter()
        .rev()
        .find(|event| event.kind == EventKind::ActionResolved)
        .unwrap();
    assert!(action.traits.plunging);
}

#[test]
fn regional_deck_cards_convert_existing_dice() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let format = MatchFormat {
        characters: 2,
        cards: 1,
        max_card_copies: 1,
    };
    let mut dice = DiceSet::default();
    dice.set(Die::Cryo, 3);
    dice.set(Die::Electro, 2);
    let player = |characters: [&str; 2]| PlayerConfig {
        characters: characters.map(str::to_owned).to_vec(),
        deck: vec!["thunder_and_eternity".to_owned()],
        active: Some(0),
        dice,
    };
    let error = Game::new_match(
        Rc::clone(&runtime),
        GameConfig {
            players: [
                player(["yae_miko", "kaeya"]),
                player(["yae_miko", "chiori"]),
            ],
            first: 0,
            seed: 7,
        },
        format,
    )
    .err()
    .unwrap();
    assert!(error.to_string().contains("inazuma"));

    let legal = player(["yae_miko", "chiori"]);
    let mut game = Game::new_match(
        runtime,
        GameConfig {
            players: [legal.clone(), legal],
            first: 0,
            seed: 7,
        },
        format,
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
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.players[0].dice.get(Die::Omni), 5);
    assert_eq!(game.state.players[0].dice.total(), 5);
}

#[test]
fn equipment_and_supports_persist_in_their_zones() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let mut game = ready("travelers_handy_sword");
    game.submit(Command::Card {
        hand: 0,
        payment: omni(2),
    })
    .unwrap();
    let decision = game.state.decision.as_ref().unwrap();
    assert_eq!(decision.options.len(), 1);
    let decision = decision.id;
    game.choose(decision, 0).unwrap();
    assert_eq!(
        game.state.players[0].characters[0].modifiers[0].definition,
        "card.travelers_handy_sword"
    );
    game.submit(Command::Skill {
        action: "ceremonial_bladework".to_owned(),
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

    let mut game = ready("paimon");
    let mut mixed = DiceSet::default();
    mixed.set(Die::Cryo, 1);
    mixed.set(Die::Hydro, 1);
    mixed.set(Die::Pyro, 1);
    game.state.players[0].dice = mixed;
    assert!(!game.action_previews().unwrap()[0].cards[0].playable);
    assert!(
        game.submit(Command::Card {
            hand: 0,
            payment: mixed,
        })
        .is_err()
    );
    let mut matching = DiceSet::default();
    matching.set(Die::Cryo, 3);
    game.state.players[0].dice = matching;
    assert!(game.action_previews().unwrap()[0].cards[0].playable);
    game.submit(Command::Card {
        hand: 0,
        payment: matching,
    })
    .unwrap();
    assert_eq!(game.state.players[0].supports[0].definition, "card.paimon");
    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert_eq!(game.state.players[0].dice.total(), 8);
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.players[0].dice.total(), 10);
}

#[test]
fn supports_extend_the_roll_phase() {
    let mut game = ready("knights_of_favonius_library");
    game.submit(Command::Card {
        hand: 0,
        payment: omni(1),
    })
    .unwrap();
    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert_eq!(game.state.players[0].rerolls, 2);
    assert_eq!(game.state.players[1].rerolls, 1);

    let payment = take(game.state.players[0].dice, 1);
    game.submit(Command::Reroll { payment }).unwrap();
    assert_eq!(game.state.turn, 0);
    assert_eq!(game.state.players[0].rerolls, 1);
    game.submit(Command::Reroll {
        payment: DiceSet::default(),
    })
    .unwrap();
    assert_eq!(game.state.turn, 1);
}

#[test]
fn food_modifies_only_the_matching_skill_kind() {
    let mut game = ready("minty_meat_rolls");
    game.submit(Command::Card {
        hand: 0,
        payment: omni(1),
    })
    .unwrap();
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();

    let previews = game.action_previews().unwrap();
    let normal = previews[0]
        .skills
        .iter()
        .find(|action| action.id == "ceremonial_bladework")
        .unwrap();
    let elemental = previews[0]
        .skills
        .iter()
        .find(|action| action.id == "frostgnaw")
        .unwrap();
    assert_eq!(normal.dice.total() + u16::from(normal.any), 2);
    assert_eq!(elemental.dice.total() + u16::from(elemental.any), 3);

    game.submit(Command::Skill {
        action: "ceremonial_bladework".to_owned(),
        payment: omni(2),
    })
    .unwrap();
    assert_eq!(
        game.state.history.last().unwrap().skill,
        Some(gicg_engine::SkillKind::NormalAttack)
    );
    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert!(!game.state.players[0].characters[0].satiated);
}

#[test]
fn revival_targets_only_defeated_characters() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let mut game = ready_with_cards(["splash", "teyvat_fried_egg"]);
    game.submit(Command::Skill {
        action: "frostgnaw".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    game.submit(Command::End).unwrap();
    for _ in 0..3 {
        game.submit(Command::Skill {
            action: "frostgnaw".to_owned(),
            payment: omni(3),
        })
        .unwrap();
    }
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();
    game.submit(Command::End).unwrap();
    for _ in 0..2 {
        game.submit(Command::Reroll {
            payment: DiceSet::default(),
        })
        .unwrap();
    }

    assert!(game.action_previews().unwrap()[1].cards[0].playable);
    let payment = take(game.state.players[1].dice, 3);
    game.submit(Command::Card { hand: 0, payment }).unwrap();
    let decision = game.state.decision.as_ref().unwrap();
    assert_eq!(decision.options.len(), 1);
    game.choose(decision.id, 0).unwrap();
    assert_eq!(
        game.state
            .counter(
                runtime.rules(),
                EntityRef::Character { player: 1, slot: 0 },
                "hp"
            )
            .unwrap(),
        3
    );
    assert!(game.state.players[1].characters[0].satiated);
    assert!(
        game.state
            .history
            .iter()
            .any(|event| event.kind == gicg_engine::EventKind::Revived)
    );
}

#[test]
fn talent_cards_equip_and_immediately_use_the_declared_skill() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let mut game = ready("cold_blooded_strike");
    game.submit(Command::Card {
        hand: 0,
        payment: omni(3),
    })
    .unwrap();
    assert_eq!(game.state.turn, 1);
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
    let talent = &game.state.players[0].characters[0].modifiers[0];
    assert_eq!(talent.definition, "talent.kaeya.cold_blooded_strike");
    assert!(game.state.history.iter().any(|event| {
        event.action_id.as_deref() == Some("frostgnaw")
            && event.skill == Some(gicg_engine::SkillKind::ElementalSkill)
    }));
}

#[test]
fn cards_search_recover_and_shuffle_cards_between_piles() {
    let mut game = ready("where_is_the_unseen_razor");
    game.state.players[0]
        .deck
        .push("travelers_handy_sword".to_owned());
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert!(
        game.state.players[0]
            .hand
            .iter()
            .any(|card| card == "travelers_handy_sword")
    );

    let mut game = ready("yesterdays_memory");
    game.state.players[0].hand[0] = "splash".to_owned();
    let mut dice = omni(31);
    dice.set(Die::Pyro, 1);
    game.state.players[0].dice = dice;
    game.submit(Command::Tune {
        hand: 0,
        die: Die::Pyro,
    })
    .unwrap();
    assert!(game.state.history.iter().any(|event| {
        event.kind == EventKind::CardDiscarded
            && event.player == 0
            && event.action_id.as_deref() == Some("splash")
    }));
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert!(
        game.state.players[0]
            .hand
            .iter()
            .any(|card| card == "splash")
    );
    assert!(
        !game.state.players[0]
            .discard
            .iter()
            .any(|card| card == "splash")
    );

    let mut game = ready("backup_supplies");
    game.submit(Command::Card {
        hand: 0,
        payment: DiceSet::default(),
    })
    .unwrap();
    assert!(
        game.state.players[0]
            .hand
            .iter()
            .any(|card| card == "splash")
    );
    assert_eq!(game.state.players[0].deck.len(), 11);
}

#[test]
fn cards_target_and_remove_enemy_summons() {
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = |character: &str, card: &str| PlayerConfig {
        characters: vec![character.to_owned()],
        deck: vec![card.to_owned(); 15],
        active: Some(0),
        dice: omni(32),
    };
    let mut game = Game::new(
        runtime,
        GameConfig {
            players: [player("chiori", "splash"), player("kaeya", "send_off")],
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
        action: "fluttering_hasode".to_owned(),
        payment: omni(3),
    })
    .unwrap();
    let decision = game.state.decision.as_ref().unwrap().id;
    game.choose(decision, 0).unwrap();
    assert_eq!(game.state.players[0].summons.len(), 1);

    game.submit(Command::Card {
        hand: 0,
        payment: omni(2),
    })
    .unwrap();
    let decision = game.state.decision.as_ref().unwrap();
    assert_eq!(decision.options.len(), 1);
    game.choose(decision.id, 0).unwrap();
    assert!(game.state.players[0].summons.is_empty());
}
