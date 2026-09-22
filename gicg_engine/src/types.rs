use crate::{EngineError, Result};
use serde::{Deserialize, Serialize};
use strum::{Display, EnumString};

pub type Counter = i32;
pub type HandlerId = u32;
pub type InstanceId = u32;
pub type DecisionId = u64;
pub type FieldId = usize;
pub type PlayerId = usize;

#[derive(Clone, Copy, Debug, Deserialize, Display, EnumString, Eq, PartialEq, Hash, Serialize)]
#[repr(u8)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
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
        parse_name(value, "element")
    }

    pub const fn die(self) -> Option<Die> {
        match self {
            Self::Physical => None,
            Self::Cryo => Some(Die::Cryo),
            Self::Hydro => Some(Die::Hydro),
            Self::Pyro => Some(Die::Pyro),
            Self::Electro => Some(Die::Electro),
            Self::Anemo => Some(Die::Anemo),
            Self::Geo => Some(Die::Geo),
            Self::Dendro => Some(Die::Dendro),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, EnumString, Eq, PartialEq, Hash)]
#[repr(u8)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
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
        parse_name(value, "die")
    }

    pub const fn index(self) -> usize {
        self as usize
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(transparent)]
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

#[derive(Clone, Copy, Debug, Deserialize, EnumString, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
pub enum Zone {
    Character,
    Combat,
    Summon,
    Support,
}

impl Zone {
    pub fn parse(value: &str) -> Result<Self> {
        parse_name(value, "zone")
    }
}

#[derive(Clone, Copy, Debug, EnumString, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
pub enum MergePolicy {
    Replace,
    Add,
    Max,
    Independent,
}

impl MergePolicy {
    pub fn parse(value: &str) -> Result<Self> {
        parse_name(value, "merge policy")
    }
}

#[derive(Clone, Copy, Debug, EnumString, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
pub enum ActionTempo {
    Combat,
    Fast,
}

impl ActionTempo {
    pub fn parse(value: &str) -> Result<Self> {
        parse_name(value, "action tempo")
    }
}

#[derive(Clone, Copy, Debug, EnumString, Eq, PartialEq, Hash)]
#[strum(serialize_all = "snake_case")]
pub enum EventKind {
    ActionResolved,
    DamageApplied,
    Switch,
    ModifierAdded,
    ModifierRemoved,
    PlayerEndDeclared,
    RoundStart,
    RoundEnd,
}

impl EventKind {
    pub fn parse(value: &str) -> Result<Self> {
        parse_name(value, "event")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EntityRef {
    Character {
        player: PlayerId,
        slot: usize,
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

fn parse_name<T: std::str::FromStr>(value: &str, kind: &str) -> Result<T> {
    value
        .parse()
        .map_err(|_| EngineError::InvalidRuleset(format!("unknown {kind} {value:?}")))
}
