use crate::{
    ChoiceOption, Counter, Die, Element, EntityRef, EventKind, PlayerId, Reaction, SkillKind,
    TargetSide,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TargetRef {
    Actor,
    Source,
    #[serde(rename = "target")]
    EventTarget,
    OwnActive,
    EnemyActive,
}

impl TargetRef {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "actor" => Some(Self::Actor),
            "source" => Some(Self::Source),
            "target" => Some(Self::EventTarget),
            "own_active" => Some(Self::OwnActive),
            "enemy_active" => Some(Self::EnemyActive),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Effect {
    AddCounter {
        target: TargetRef,
        name: String,
        delta: Counter,
    },
    Damage {
        target: TargetRef,
        element: Element,
        amount: u32,
    },
    Heal {
        target: TargetRef,
        amount: u32,
    },
    Revive {
        target: TargetRef,
        amount: u32,
    },
    AddModifier {
        target: TargetRef,
        definition: String,
    },
    AddModifierCounter {
        definition: String,
        name: String,
        delta: Counter,
    },
    AddCharacterCounter {
        character: String,
        name: String,
        delta: Counter,
    },
    RemoveModifier {
        definition: String,
    },
    RemoveTarget {
        target: TargetRef,
    },
    AddCard {
        card: String,
    },
    AddDice {
        die: Die,
        count: u8,
    },
    Draw {
        count: u8,
    },
    Discard {
        side: TargetSide,
        count: u8,
    },
    DrawCard {
        card: String,
    },
    RecoverCard {
        card: String,
    },
    AddDeckCard {
        card: String,
        count: u8,
    },
    UseSkill {
        action: String,
    },
    CompleteSkill {
        action: String,
        skill: SkillKind,
    },
    Choice {
        options: Vec<ChoiceOption>,
        continuation: String,
    },
}

#[derive(Clone, Debug, Serialize)]
pub struct Event {
    pub kind: EventKind,
    pub actor: Option<EntityRef>,
    pub source: Option<EntityRef>,
    pub target: Option<EntityRef>,
    pub player: PlayerId,
    pub action_id: Option<String>,
    pub skill: Option<SkillKind>,
    pub element: Option<Element>,
    pub reaction: Option<Reaction>,
    pub amount: Counter,
}

#[derive(Clone, Debug, Default)]
pub struct RuleContext {
    pub actor: Option<EntityRef>,
    pub source: Option<EntityRef>,
    pub target: Option<EntityRef>,
    pub event: Option<Event>,
    pub action_id: Option<String>,
    pub skill: Option<SkillKind>,
    pub option: Option<String>,
}
