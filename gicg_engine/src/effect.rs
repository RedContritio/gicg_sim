use crate::{ChoiceOption, Counter, Element, EntityRef, EventKind, PlayerId, RemovalReason};
use serde::Deserialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TargetRef {
    Actor,
    Source,
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
    SetCounter {
        target: TargetRef,
        name: String,
        value: Counter,
    },
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
    AddModifier {
        target: TargetRef,
        definition: String,
    },
    RemoveModifier {
        target: TargetRef,
        reason: RemovalReason,
    },
    Choice {
        options: Vec<ChoiceOption>,
        continuation: String,
    },
    ActivateAbility {
        target: TargetRef,
        ability: String,
    },
}

#[derive(Clone, Debug)]
pub struct Event {
    pub kind: EventKind,
    pub actor: Option<EntityRef>,
    pub source: Option<EntityRef>,
    pub target: Option<EntityRef>,
    pub player: PlayerId,
    pub action_id: Option<String>,
    pub element: Option<Element>,
    pub amount: Counter,
}

#[derive(Clone, Debug, Default)]
pub struct RuleContext {
    pub actor: Option<EntityRef>,
    pub source: Option<EntityRef>,
    pub target: Option<EntityRef>,
    pub event: Option<Event>,
    pub action_id: Option<String>,
    pub option: Option<String>,
}
