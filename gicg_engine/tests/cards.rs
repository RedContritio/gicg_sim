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
    let runtime = Rc::new(LuaRuntime::load("../data/native_latest").unwrap());
    let player = |card: &str| PlayerConfig {
        characters: vec!["kaeya".to_owned(), "kaeya".to_owned()],
        deck: vec![card.to_owned(); 15],
        active: Some(0),
        dice: omni(32),
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
    let decision = game.state.decision.as_ref().unwrap().id;
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
    game.submit(Command::Card {
        hand: 0,
        payment: matching,
    })
    .unwrap();
    assert_eq!(game.state.players[0].supports[0].definition, "card.paimon");
    game.submit(Command::End).unwrap();
    game.submit(Command::End).unwrap();
    assert_eq!(game.state.players[0].dice.total(), 10);
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
