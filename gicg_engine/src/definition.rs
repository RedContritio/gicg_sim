use std::collections::{HashMap, HashSet};

use serde::Serialize;

use crate::{
    ActionKind, ActionTempo, Counter, DiceSet, Die, EngineError, EventKind, FieldId, HandlerId,
    MergePolicy, Result, Zone,
};

#[derive(Clone, Debug, Serialize)]
pub struct CounterDefinition {
    pub name: String,
    pub initial: Counter,
    pub min: Counter,
    pub max: Counter,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct CounterSchema {
    fields: Vec<CounterDefinition>,
}

impl CounterSchema {
    pub fn new(mut fields: Vec<CounterDefinition>) -> Result<Self> {
        fields.sort_unstable_by(|left, right| left.name.cmp(&right.name));
        for (index, field) in fields.iter().enumerate() {
            if field.name.is_empty() {
                return Err(EngineError::InvalidRuleset(
                    "counter name is empty".to_owned(),
                ));
            }
            if field.min > field.max || !(field.min..=field.max).contains(&field.initial) {
                return Err(EngineError::InvalidRuleset(format!(
                    "counter {:?} has invalid range [{}, {}] and initial value {}",
                    field.name, field.min, field.max, field.initial
                )));
            }
            if index > 0 && fields[index - 1].name == field.name {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate counter {:?}",
                    field.name
                )));
            }
        }
        Ok(Self { fields })
    }

    pub fn field(&self, name: &str) -> Option<FieldId> {
        self.fields
            .binary_search_by_key(&name, |field| field.name.as_str())
            .ok()
    }

    pub fn definition(&self, field: FieldId) -> Option<&CounterDefinition> {
        self.fields.get(field)
    }

    pub fn fields(&self) -> &[CounterDefinition] {
        &self.fields
    }

    pub fn initial_values(&self) -> Vec<Counter> {
        self.fields.iter().map(|field| field.initial).collect()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CounterConsume {
    None,
    Fixed(Counter),
    All,
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct CounterCost {
    pub field: FieldId,
    pub require: Counter,
    pub consume: CounterConsume,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct Cost {
    pub dice: DiceSet,
    pub any: u8,
    pub counters: Vec<CounterCost>,
}

impl Cost {
    pub fn dice_total(&self) -> u16 {
        self.dice.total() + u16::from(self.any)
    }

    pub fn valid_payment(&self, inventory: DiceSet, payment: DiceSet) -> bool {
        if payment.total() != self.dice_total() {
            return false;
        }
        if Die::ALL
            .iter()
            .any(|die| payment.get(*die) > inventory.get(*die))
        {
            return false;
        }
        let missing: u16 = Die::ALL[..Die::Omni.index()]
            .iter()
            .map(|die| self.dice.get(*die).saturating_sub(payment.get(*die)))
            .map(u16::from)
            .sum();
        u16::from(payment.get(Die::Omni)) >= missing
    }

    pub fn reduce_dice(&mut self, amount: u8) -> u8 {
        let mut remaining = amount;
        let reduced_any = self.any.min(remaining);
        self.any -= reduced_any;
        remaining -= reduced_any;
        for die in Die::ALL[..Die::Omni.index()].iter().copied() {
            let reduced = self.dice.get(die).min(remaining);
            self.dice.0[die.index()] -= reduced;
            remaining -= reduced;
        }
        amount - remaining
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct ActionDefinition {
    pub id: String,
    pub name: String,
    pub tempo: ActionTempo,
    pub cost: Cost,
    #[serde(skip)]
    pub resolve: HandlerId,
    #[serde(skip)]
    pub continuations: HashMap<String, HandlerId>,
}

#[derive(Clone, Debug, Serialize)]
pub struct CharacterDefinition {
    pub id: String,
    pub name: String,
    pub element: crate::Element,
    pub counters: CounterSchema,
    pub actions: Vec<ActionDefinition>,
}

#[derive(Clone, Debug, Serialize)]
pub struct CardDefinition {
    pub id: String,
    pub name: String,
    pub description: String,
    pub action: ActionDefinition,
}

impl CharacterDefinition {
    pub fn new(
        id: String,
        name: String,
        element: crate::Element,
        counters: CounterSchema,
        actions: Vec<ActionDefinition>,
    ) -> Result<Self> {
        let mut ids = HashSet::new();
        for action in &actions {
            if !ids.insert(&action.id) {
                return Err(EngineError::InvalidRuleset(format!(
                    "character {id:?} has duplicate action {:?}",
                    action.id
                )));
            }
        }
        Ok(Self {
            id,
            name,
            element,
            counters,
            actions,
        })
    }

    pub fn action(&self, id: &str) -> Option<&ActionDefinition> {
        self.actions.iter().find(|action| action.id == id)
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct ModifierDefinition {
    pub id: String,
    pub name: String,
    pub zone: Zone,
    pub counters: CounterSchema,
    pub merge: MergePolicy,
    pub remove_at_zero: Option<FieldId>,
    pub damage: Option<DamageModifierDefinition>,
    pub action: Option<ActionModifierDefinition>,
    #[serde(skip)]
    pub handlers: HashMap<EventKind, HandlerId>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DamageDirection {
    Outgoing,
    Incoming,
}

#[derive(Clone, Debug, Serialize)]
pub struct DamageModifierDefinition {
    pub direction: DamageDirection,
    pub elements: Vec<crate::Element>,
    pub delta: Counter,
    pub set_element: Option<crate::Element>,
    pub counter: Option<String>,
    pub consume: Counter,
    pub shield: Option<String>,
    pub active_only: bool,
    pub include_piercing: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct ActionModifierDefinition {
    pub kinds: Vec<ActionKind>,
    pub actions: Vec<String>,
    pub reduce_dice: u8,
    pub tempo: Option<ActionTempo>,
    pub counter: Option<String>,
    pub consume: Counter,
}

#[derive(Debug, Serialize)]
pub struct Ruleset {
    pub hash: String,
    pub characters: Vec<CharacterDefinition>,
    pub modifiers: Vec<ModifierDefinition>,
    pub cards: Vec<CardDefinition>,
}

impl Ruleset {
    pub(crate) fn new(
        hash: String,
        characters: Vec<CharacterDefinition>,
        modifiers: Vec<ModifierDefinition>,
        cards: Vec<CardDefinition>,
    ) -> Result<Self> {
        let mut ids = HashSet::new();
        for id in characters
            .iter()
            .map(|value| &value.id)
            .chain(modifiers.iter().map(|value| &value.id))
            .chain(cards.iter().map(|value| &value.id))
        {
            if !ids.insert(id) {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate definition id {id:?}"
                )));
            }
        }
        Ok(Self {
            hash,
            characters,
            modifiers,
            cards,
        })
    }

    pub fn character(&self, id: &str) -> Option<&CharacterDefinition> {
        self.characters
            .iter()
            .find(|definition| definition.id == id)
    }

    pub fn modifier(&self, id: &str) -> Option<&ModifierDefinition> {
        self.modifiers.iter().find(|definition| definition.id == id)
    }

    pub fn card(&self, id: &str) -> Option<&CardDefinition> {
        self.cards.iter().find(|definition| definition.id == id)
    }
}
