use std::collections::{HashMap, HashSet};

use serde::Serialize;

use crate::{
    ActionKind, ActionTempo, ActionTraits, CardKind, CardTargetKind, Counter, DiceSet, Die,
    EngineError, EventKind, FieldId, HandlerId, MergePolicy, Result, SkillKind, TargetSide,
    TargetState, Zone,
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
    pub same: u8,
    pub counters: Vec<CounterCost>,
}

impl Cost {
    pub fn dice_total(&self) -> u16 {
        self.dice.total() + u16::from(self.any) + u16::from(self.same)
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
        let omni = u16::from(payment.get(Die::Omni));
        if omni < missing {
            return false;
        }
        self.same == 0 || self.valid_same_payment(payment, (omni - missing) as u8)
    }

    pub fn can_pay(&self, inventory: DiceSet) -> bool {
        if self.dice_total() > inventory.total() {
            return false;
        }
        if self.same == 0 {
            return self.can_pay_after_same(inventory);
        }
        Die::ALL[..Die::Omni.index()].iter().copied().any(|die| {
            let available = inventory.get(die).min(self.same);
            (0..=available).any(|native| {
                let omni = self.same - native;
                if omni > inventory.get(Die::Omni) {
                    return false;
                }
                let mut remaining = inventory;
                remaining.0[die.index()] -= native;
                remaining.0[Die::Omni.index()] -= omni;
                self.can_pay_after_same(remaining)
            })
        })
    }

    fn can_pay_after_same(&self, inventory: DiceSet) -> bool {
        let mut omni = inventory.get(Die::Omni);
        for die in Die::ALL[..Die::Omni.index()].iter().copied() {
            let missing = self.dice.get(die).saturating_sub(inventory.get(die));
            if missing > omni {
                return false;
            }
            omni -= missing;
        }
        true
    }

    fn valid_same_payment(&self, payment: DiceSet, omni: u8) -> bool {
        let matching = Die::ALL[..Die::Omni.index()]
            .iter()
            .map(|die| payment.get(*die).saturating_sub(self.dice.get(*die)))
            .max()
            .unwrap_or(0);
        self.same <= matching.saturating_add(omni)
    }

    pub fn reduce_dice(&mut self, amount: u8) -> u8 {
        let mut remaining = amount;
        let reduced_any = self.any.min(remaining);
        self.any -= reduced_any;
        remaining -= reduced_any;
        let reduced_same = self.same.min(remaining);
        self.same -= reduced_same;
        remaining -= reduced_same;
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
    pub skill: Option<SkillKind>,
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
    pub kind: CardKind,
    pub target: Option<CardTargetDefinition>,
    pub talent: Option<TalentDefinition>,
    pub action: ActionDefinition,
}

#[derive(Clone, Debug, Serialize)]
pub struct TalentDefinition {
    pub character: String,
    pub action: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct CardTargetDefinition {
    pub kind: CardTargetKind,
    pub side: TargetSide,
    pub state: TargetState,
    pub damaged: bool,
    pub active_only: bool,
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
    pub slot: Option<String>,
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
    pub traits: ActionTraits,
}

#[derive(Clone, Debug, Serialize)]
pub struct ActionModifierDefinition {
    pub kinds: Vec<ActionKind>,
    pub skills: Vec<SkillKind>,
    pub actions: Vec<String>,
    pub reduce_dice: u8,
    pub tempo: Option<ActionTempo>,
    pub counter: Option<String>,
    pub consume: Counter,
    pub traits: ActionTraits,
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
        for card in &cards {
            validate_card_target(card)?;
            validate_talent(card, &characters)?;
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

fn validate_card_target(card: &CardDefinition) -> Result<()> {
    let Some(target) = &card.target else {
        return Ok(());
    };
    if matches!(card.kind, CardKind::Food | CardKind::Equipment)
        && target.kind != CardTargetKind::Character
    {
        return Err(EngineError::InvalidRuleset(format!(
            "card {:?} requires a character target",
            card.id
        )));
    }
    if target.kind != CardTargetKind::Character
        && (target.state != TargetState::Alive || target.damaged || target.active_only)
    {
        return Err(EngineError::InvalidRuleset(format!(
            "card {:?} uses character filters on a non-character target",
            card.id
        )));
    }
    Ok(())
}

fn validate_talent(card: &CardDefinition, characters: &[CharacterDefinition]) -> Result<()> {
    let Some(talent) = &card.talent else {
        return Ok(());
    };
    let character = characters
        .iter()
        .find(|character| character.id == talent.character)
        .ok_or_else(|| {
            EngineError::InvalidRuleset(format!(
                "talent card {:?} references missing character {:?}",
                card.id, talent.character
            ))
        })?;
    if character.action(&talent.action).is_none() {
        return Err(EngineError::InvalidRuleset(format!(
            "talent card {:?} references missing action {:?}",
            card.id, talent.action
        )));
    }
    if card.target.is_some() {
        return Err(EngineError::InvalidRuleset(format!(
            "talent card {:?} cannot define a target",
            card.id
        )));
    }
    Ok(())
}
