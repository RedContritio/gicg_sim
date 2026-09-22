use std::collections::HashMap;

use crate::{
    ActionTags, ActionTempo, Counter, DefinitionId, DiceSet, Die, EngineError, EventKind, FieldId,
    HandlerId, MergePolicy, Result, Zone,
};

#[derive(Clone, Debug)]
pub struct CounterDefinition {
    pub name: String,
    pub initial: Counter,
    pub min: Counter,
    pub max: Counter,
}

#[derive(Clone, Debug, Default)]
pub struct CounterSchema {
    fields: Vec<CounterDefinition>,
    by_name: HashMap<String, FieldId>,
}

impl CounterSchema {
    pub fn new(mut fields: Vec<CounterDefinition>) -> Result<Self> {
        fields.sort_unstable_by(|left, right| left.name.cmp(&right.name));
        let mut by_name = HashMap::with_capacity(fields.len());
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
            let field_id = FieldId::try_from(index).map_err(|_| {
                EngineError::InvalidRuleset("one entity declares too many counters".to_owned())
            })?;
            if by_name.insert(field.name.clone(), field_id).is_some() {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate counter {:?}",
                    field.name
                )));
            }
        }
        Ok(Self { fields, by_name })
    }

    pub fn field(&self, name: &str) -> Option<FieldId> {
        self.by_name.get(name).copied()
    }

    pub fn definition(&self, field: FieldId) -> Option<&CounterDefinition> {
        self.fields.get(usize::from(field))
    }

    pub fn fields(&self) -> &[CounterDefinition] {
        &self.fields
    }

    pub fn initial_values(&self) -> Vec<Counter> {
        self.fields.iter().map(|field| field.initial).collect()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CounterConsume {
    None,
    Fixed(Counter),
    All,
}

#[derive(Clone, Copy, Debug)]
pub struct CounterCost {
    pub field: FieldId,
    pub require: Counter,
    pub consume: CounterConsume,
}

#[derive(Clone, Debug, Default)]
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
}

#[derive(Clone, Debug)]
pub struct ActionDefinition {
    pub id: String,
    pub name: String,
    pub tags: ActionTags,
    pub tempo: ActionTempo,
    pub cost: Cost,
    pub resolve: HandlerId,
    pub continuations: HashMap<String, HandlerId>,
}

#[derive(Clone, Debug)]
pub struct CharacterDefinition {
    pub definition: DefinitionId,
    pub id: String,
    pub name: String,
    pub element: crate::Element,
    pub counters: CounterSchema,
    pub actions: Vec<ActionDefinition>,
    action_by_id: HashMap<String, usize>,
}

#[derive(Clone, Debug)]
pub struct CardDefinition {
    pub definition: DefinitionId,
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
        let mut action_by_id = HashMap::with_capacity(actions.len());
        for (index, action) in actions.iter().enumerate() {
            if action_by_id.insert(action.id.clone(), index).is_some() {
                return Err(EngineError::InvalidRuleset(format!(
                    "character {id:?} has duplicate action {:?}",
                    action.id
                )));
            }
        }
        Ok(Self {
            definition: 0,
            id,
            name,
            element,
            counters,
            actions,
            action_by_id,
        })
    }

    pub fn action(&self, id: &str) -> Option<&ActionDefinition> {
        self.action_by_id.get(id).map(|index| &self.actions[*index])
    }
}

#[derive(Clone, Copy, Debug)]
pub struct HandlerDefinition {
    pub event: EventKind,
    pub priority: i16,
    pub handler: HandlerId,
}

#[derive(Clone, Debug)]
pub struct ModifierDefinition {
    pub definition: DefinitionId,
    pub id: String,
    pub name: String,
    pub zone: Zone,
    pub counters: CounterSchema,
    pub merge: MergePolicy,
    pub remove_at_zero: Option<FieldId>,
    pub handlers: HashMap<EventKind, Vec<HandlerDefinition>>,
    pub abilities: HashMap<String, HandlerId>,
}

#[derive(Debug)]
pub struct Ruleset {
    pub hash: String,
    pub characters: Vec<CharacterDefinition>,
    pub modifiers: Vec<ModifierDefinition>,
    pub cards: Vec<CardDefinition>,
    character_by_id: HashMap<String, usize>,
    modifier_by_id: HashMap<String, usize>,
    card_by_id: HashMap<String, usize>,
    character_by_definition: HashMap<DefinitionId, usize>,
    modifier_by_definition: HashMap<DefinitionId, usize>,
    card_by_definition: HashMap<DefinitionId, usize>,
}

impl Ruleset {
    pub(crate) fn new(
        hash: String,
        mut characters: Vec<CharacterDefinition>,
        mut modifiers: Vec<ModifierDefinition>,
        mut cards: Vec<CardDefinition>,
    ) -> Result<Self> {
        let mut ids = HashMap::<String, ()>::new();
        let mut character_by_id = HashMap::new();
        let mut modifier_by_id = HashMap::new();
        let mut card_by_id = HashMap::new();
        let mut character_by_definition = HashMap::new();
        let mut modifier_by_definition = HashMap::new();
        let mut card_by_definition = HashMap::new();
        let mut next_definition = 1;
        for (index, character) in characters.iter_mut().enumerate() {
            if ids.insert(character.id.clone(), ()).is_some() {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate definition id {:?}",
                    character.id
                )));
            }
            character.definition = next_definition;
            next_definition += 1;
            character_by_id.insert(character.id.clone(), index);
            character_by_definition.insert(character.definition, index);
        }
        for (index, modifier) in modifiers.iter_mut().enumerate() {
            if ids.insert(modifier.id.clone(), ()).is_some() {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate definition id {:?}",
                    modifier.id
                )));
            }
            modifier.definition = next_definition;
            next_definition += 1;
            modifier_by_id.insert(modifier.id.clone(), index);
            modifier_by_definition.insert(modifier.definition, index);
        }
        for (index, card) in cards.iter_mut().enumerate() {
            if ids.insert(card.id.clone(), ()).is_some() {
                return Err(EngineError::InvalidRuleset(format!(
                    "duplicate definition id {:?}",
                    card.id
                )));
            }
            card.definition = next_definition;
            next_definition += 1;
            card_by_id.insert(card.id.clone(), index);
            card_by_definition.insert(card.definition, index);
        }
        Ok(Self {
            hash,
            characters,
            modifiers,
            cards,
            character_by_id,
            modifier_by_id,
            card_by_id,
            character_by_definition,
            modifier_by_definition,
            card_by_definition,
        })
    }

    pub fn character(&self, id: &str) -> Option<&CharacterDefinition> {
        self.character_by_id
            .get(id)
            .map(|index| &self.characters[*index])
    }

    pub fn character_definition(&self, id: DefinitionId) -> Option<&CharacterDefinition> {
        self.character_by_definition
            .get(&id)
            .map(|index| &self.characters[*index])
    }

    pub fn modifier(&self, id: &str) -> Option<&ModifierDefinition> {
        self.modifier_by_id
            .get(id)
            .map(|index| &self.modifiers[*index])
    }

    pub fn modifier_definition(&self, id: DefinitionId) -> Option<&ModifierDefinition> {
        self.modifier_by_definition
            .get(&id)
            .map(|index| &self.modifiers[*index])
    }

    pub fn card(&self, id: &str) -> Option<&CardDefinition> {
        self.card_by_id.get(id).map(|index| &self.cards[*index])
    }

    pub fn card_definition(&self, id: DefinitionId) -> Option<&CardDefinition> {
        self.card_by_definition
            .get(&id)
            .map(|index| &self.cards[*index])
    }
}
