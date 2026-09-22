use std::fmt;

use crate::{EngineError, Result};

pub type Counter = i32;
pub type DefinitionId = u32;
pub type HandlerId = u32;
pub type InstanceId = u32;
pub type DecisionId = u64;
pub type FieldId = u16;
pub type PlayerId = u8;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
#[repr(u8)]
pub enum Element {
    Physical,
    Cryo,
    Hydro,
    Pyro,
    Electro,
    Anemo,
    Geo,
    Dendro,
}

impl Element {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "physical" => Ok(Self::Physical),
            "cryo" => Ok(Self::Cryo),
            "hydro" => Ok(Self::Hydro),
            "pyro" => Ok(Self::Pyro),
            "electro" => Ok(Self::Electro),
            "anemo" => Ok(Self::Anemo),
            "geo" => Ok(Self::Geo),
            "dendro" => Ok(Self::Dendro),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown element {value:?}"
            ))),
        }
    }
}

impl fmt::Display for Element {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Physical => "physical",
            Self::Cryo => "cryo",
            Self::Hydro => "hydro",
            Self::Pyro => "pyro",
            Self::Electro => "electro",
            Self::Anemo => "anemo",
            Self::Geo => "geo",
            Self::Dendro => "dendro",
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
#[repr(u8)]
pub enum Die {
    Cryo,
    Hydro,
    Pyro,
    Electro,
    Anemo,
    Geo,
    Dendro,
    Omni,
}

impl Die {
    pub const COUNT: usize = 8;
    pub const ALL: [Self; Self::COUNT] = [
        Self::Cryo,
        Self::Hydro,
        Self::Pyro,
        Self::Electro,
        Self::Anemo,
        Self::Geo,
        Self::Dendro,
        Self::Omni,
    ];

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "cryo" => Ok(Self::Cryo),
            "hydro" => Ok(Self::Hydro),
            "pyro" => Ok(Self::Pyro),
            "electro" => Ok(Self::Electro),
            "anemo" => Ok(Self::Anemo),
            "geo" => Ok(Self::Geo),
            "dendro" => Ok(Self::Dendro),
            "omni" => Ok(Self::Omni),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown die {value:?}"
            ))),
        }
    }

    pub const fn index(self) -> usize {
        self as usize
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DiceSet(pub [u8; Die::COUNT]);

impl DiceSet {
    pub fn get(self, die: Die) -> u8 {
        self.0[die.index()]
    }

    pub fn set(&mut self, die: Die, value: u8) {
        self.0[die.index()] = value;
    }

    pub fn total(self) -> u16 {
        self.0.iter().map(|value| u16::from(*value)).sum()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Zone {
    Character,
    Combat,
    Summon,
    Support,
}

impl Zone {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "character" => Ok(Self::Character),
            "combat" => Ok(Self::Combat),
            "summon" => Ok(Self::Summon),
            "support" => Ok(Self::Support),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown zone {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MergePolicy {
    Replace,
    Add,
    Max,
    Independent,
}

impl MergePolicy {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "replace" => Ok(Self::Replace),
            "add" => Ok(Self::Add),
            "max" => Ok(Self::Max),
            "independent" => Ok(Self::Independent),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown merge policy {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ActionTempo {
    Combat,
    Fast,
}

impl ActionTempo {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "combat" => Ok(Self::Combat),
            "fast" => Ok(Self::Fast),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown action tempo {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ActionTags(pub u32);

impl ActionTags {
    pub const SKILL: u32 = 1 << 0;
    pub const NORMAL: u32 = 1 << 1;
    pub const ELEMENTAL_SKILL: u32 = 1 << 2;
    pub const BURST: u32 = 1 << 3;
    pub const CARD: u32 = 1 << 4;
    pub const SWITCH: u32 = 1 << 5;
    pub const TECHNIQUE: u32 = 1 << 6;
    pub const CHARGED: u32 = 1 << 7;
    pub const PREPARED: u32 = 1 << 8;

    pub fn insert_name(&mut self, value: &str) -> Result<()> {
        self.0 |= match value {
            "skill" => Self::SKILL,
            "normal" => Self::NORMAL,
            "elemental_skill" => Self::ELEMENTAL_SKILL,
            "burst" => Self::BURST,
            "card" => Self::CARD,
            "switch" => Self::SWITCH,
            "technique" => Self::TECHNIQUE,
            "charged" => Self::CHARGED,
            "prepared" => Self::PREPARED,
            _ => {
                return Err(EngineError::InvalidRuleset(format!(
                    "unknown action tag {value:?}"
                )));
            }
        };
        Ok(())
    }

    pub const fn contains(self, tag: u32) -> bool {
        self.0 & tag != 0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum EventKind {
    ActionResolved,
    DamageApplied,
    Switch,
    ModifierAdded,
    ModifierRemoved,
    PlayerEndDeclared,
    DecisionStart,
    RoundStart,
    RoundEnd,
}

impl EventKind {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "action_resolved" => Ok(Self::ActionResolved),
            "damage_applied" => Ok(Self::DamageApplied),
            "switch" => Ok(Self::Switch),
            "modifier_added" => Ok(Self::ModifierAdded),
            "modifier_removed" => Ok(Self::ModifierRemoved),
            "player_end_declared" => Ok(Self::PlayerEndDeclared),
            "decision_start" => Ok(Self::DecisionStart),
            "round_start" => Ok(Self::RoundStart),
            "round_end" => Ok(Self::RoundEnd),
            _ => Err(EngineError::InvalidRuleset(format!(
                "unknown event {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EntityRef {
    Character {
        player: PlayerId,
        slot: u8,
    },
    Modifier {
        player: PlayerId,
        instance: InstanceId,
    },
}

impl EntityRef {
    pub const fn player(self) -> PlayerId {
        match self {
            Self::Character { player, .. } | Self::Modifier { player, .. } => player,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RemovalReason {
    Consumed,
    Exhausted,
    Expired,
    Discarded,
    Replaced,
    Death,
}
