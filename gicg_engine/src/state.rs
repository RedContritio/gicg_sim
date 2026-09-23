use crate::{
    Counter, CounterSchema, DiceSet, Element, EngineError, EntityRef, Event, InstanceId, PlayerId,
    Reaction, Result, Ruleset, Zone,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    SelectActive,
    Redraw,
    Roll,
    Action,
    Finished,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FinishReason {
    Defeat,
    Concede,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ChoiceOption {
    pub id: String,
    pub label: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Decision {
    pub id: crate::DecisionId,
    pub player: PlayerId,
    pub options: Vec<ChoiceOption>,
}

#[derive(Clone, Debug, Serialize)]
pub struct GameState {
    pub round: u16,
    pub phase: Phase,
    pub turn: PlayerId,
    pub winner: Option<PlayerId>,
    pub finish_reason: Option<FinishReason>,
    pub decision: Option<Decision>,
    pub last_reaction: Option<ReactionRecord>,
    pub history: Vec<Event>,
    pub players: [PlayerState; 2],
    pub next_instance: InstanceId,
    pub next_decision: crate::DecisionId,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct PlayerState {
    pub characters: Vec<CharacterState>,
    pub active: usize,
    pub dice: DiceSet,
    pub rerolls: u8,
    pub deck: Vec<String>,
    pub hand: Vec<String>,
    pub discard: Vec<String>,
    pub ended: bool,
    pub combat: Vec<ModifierState>,
    pub summons: Vec<ModifierState>,
    pub supports: Vec<ModifierState>,
}

#[derive(Clone, Debug, Serialize)]
pub struct CharacterState {
    pub definition: String,
    pub counters: Vec<Counter>,
    pub auras: Vec<Element>,
    pub satiated: bool,
    pub modifiers: Vec<ModifierState>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct ReactionRecord {
    pub kind: Reaction,
    pub player: PlayerId,
    pub slot: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct ModifierState {
    pub instance: InstanceId,
    pub definition: String,
    pub counters: Vec<Counter>,
}

#[derive(Clone, Debug)]
pub struct PlayerConfig {
    pub characters: Vec<String>,
    pub deck: Vec<String>,
    pub active: Option<usize>,
    pub dice: DiceSet,
}

#[derive(Clone, Debug)]
pub struct GameConfig {
    pub players: [PlayerConfig; 2],
    pub first: PlayerId,
    pub seed: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct MatchFormat {
    pub characters: usize,
    pub cards: usize,
    pub max_card_copies: usize,
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct GameSignals {
    pub healing: [i32; 2],
    pub shields: [i32; 2],
    pub reactions: [i32; 2],
    pub kills: [i32; 2],
    pub energy_overflow: [i32; 2],
    pub dice_wasted: [i32; 2],
}

impl MatchFormat {
    pub fn validate(self, rules: &Ruleset, config: &GameConfig) -> Result<()> {
        if self.characters == 0 || self.cards == 0 || self.max_card_copies == 0 {
            return Err(EngineError::InvalidGame(
                "match format limits must be positive".to_owned(),
            ));
        }
        for (player, player_config) in config.players.iter().enumerate() {
            self.validate_player(rules, player, player_config)?;
        }
        Ok(())
    }

    fn validate_player(
        self,
        rules: &Ruleset,
        player: PlayerId,
        config: &PlayerConfig,
    ) -> Result<()> {
        if config.characters.len() != self.characters {
            return Err(EngineError::InvalidGame(format!(
                "player {player} must select {} characters",
                self.characters
            )));
        }
        if config.deck.len() != self.cards {
            return Err(EngineError::InvalidGame(format!(
                "player {player} deck must contain {} cards",
                self.cards
            )));
        }
        let mut characters = config.characters.clone();
        characters.sort_unstable();
        if characters.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(EngineError::InvalidGame(format!(
                "player {player} cannot select the same character twice"
            )));
        }
        let mut copies = HashMap::new();
        for card in &config.deck {
            let count = copies.entry(card).or_insert(0usize);
            *count += 1;
            if *count > self.max_card_copies {
                return Err(EngineError::InvalidGame(format!(
                    "player {player} has too many copies of card {card:?}"
                )));
            }
            if let Some(definition) = rules.card(card) {
                validate_card_deck(rules, player, config, definition)?;
            }
        }
        Ok(())
    }
}

fn validate_card_deck(
    rules: &Ruleset,
    player: PlayerId,
    config: &PlayerConfig,
    card: &crate::CardDefinition,
) -> Result<()> {
    if let Some(talent) = &card.talent
        && !config.characters.contains(&talent.character)
    {
        return Err(EngineError::InvalidGame(format!(
            "player {player} talent card {:?} requires character {:?}",
            card.id, talent.character
        )));
    }
    for requirement in &card.deck_requirements {
        let count = config
            .characters
            .iter()
            .filter_map(|id| rules.character(id))
            .filter(|character| character.has_tag(&requirement.tag))
            .count();
        if count < requirement.count {
            return Err(EngineError::InvalidGame(format!(
                "player {player} card {:?} requires {} characters tagged {:?}",
                card.id, requirement.count, requirement.tag
            )));
        }
    }
    Ok(())
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct ModifierLocation {
    pub player: PlayerId,
    pub zone: Zone,
    pub host: usize,
    pub index: usize,
}

impl GameState {
    pub(crate) fn new(rules: &Ruleset, config: GameConfig) -> Result<Self> {
        if config.first > 1 {
            return Err(EngineError::InvalidGame(format!(
                "first player {} is invalid",
                config.first
            )));
        }
        let phase = initial_phase(&config.players)?;
        let mut players = [PlayerState::default(), PlayerState::default()];
        for (player_id, player_config) in config.players.into_iter().enumerate() {
            players[player_id] = build_player(rules, player_id, player_config)?;
        }
        Ok(Self {
            round: 1,
            phase,
            turn: config.first,
            winner: None,
            finish_reason: None,
            decision: None,
            last_reaction: None,
            history: Vec::new(),
            players,
            next_instance: 1,
            next_decision: 1,
        })
    }

    pub fn active_character(&self, player: PlayerId) -> EntityRef {
        EntityRef::Character {
            player,
            slot: self.players[player].active,
        }
    }

    pub fn character(&self, player: PlayerId, slot: usize) -> Result<&CharacterState> {
        self.players[player].characters.get(slot).ok_or_else(|| {
            EngineError::InvalidCommand(format!("character {player}:{slot} does not exist"))
        })
    }

    pub(crate) fn character_mut(
        &mut self,
        player: PlayerId,
        slot: usize,
    ) -> Result<&mut CharacterState> {
        self.players[player]
            .characters
            .get_mut(slot)
            .ok_or_else(|| {
                EngineError::InvalidCommand(format!("character {player}:{slot} does not exist"))
            })
    }

    pub fn counter(&self, rules: &Ruleset, entity: EntityRef, name: &str) -> Result<Counter> {
        let (schema, values) = self.entity_counters(rules, entity)?;
        let field = schema.field(name).ok_or_else(|| {
            EngineError::Rule(format!("entity {entity:?} has no counter {name:?}"))
        })?;
        Ok(values[field])
    }

    pub(crate) fn set_counter(
        &mut self,
        rules: &Ruleset,
        entity: EntityRef,
        name: &str,
        value: Counter,
    ) -> Result<()> {
        let (schema, values) = self.entity_counters_mut(rules, entity)?;
        let field = schema.field(name).ok_or_else(|| {
            EngineError::Rule(format!("entity {entity:?} has no counter {name:?}"))
        })?;
        let definition = schema.definition(field).expect("field belongs to schema");
        if !(definition.min..=definition.max).contains(&value) {
            return Err(EngineError::Rule(format!(
                "counter {name:?} value {value} is outside [{}, {}]",
                definition.min, definition.max
            )));
        }
        values[field] = value;
        Ok(())
    }

    pub(crate) fn counter_range(
        &self,
        rules: &Ruleset,
        entity: EntityRef,
        name: &str,
    ) -> Result<(Counter, Counter)> {
        let (schema, _) = self.entity_counters(rules, entity)?;
        let field = schema.field(name).ok_or_else(|| {
            EngineError::Rule(format!("entity {entity:?} has no counter {name:?}"))
        })?;
        let definition = schema.definition(field).expect("field belongs to schema");
        Ok((definition.min, definition.max))
    }

    fn entity_counters<'a>(
        &'a self,
        rules: &'a Ruleset,
        entity: EntityRef,
    ) -> Result<(&'a CounterSchema, &'a [Counter])> {
        match entity {
            EntityRef::Character { player, slot } => {
                let character = self.character(player, slot)?;
                let definition = rules
                    .character(&character.definition)
                    .expect("state references a loaded character");
                Ok((&definition.counters, &character.counters))
            }
            EntityRef::Modifier { instance, .. } => {
                let (_, modifier) = self.find_modifier(instance).ok_or_else(|| {
                    EngineError::Rule(format!("modifier instance {instance} is not active"))
                })?;
                let definition = rules
                    .modifier(&modifier.definition)
                    .expect("state references a loaded modifier");
                Ok((&definition.counters, &modifier.counters))
            }
        }
    }

    fn entity_counters_mut<'a>(
        &'a mut self,
        rules: &'a Ruleset,
        entity: EntityRef,
    ) -> Result<(&'a CounterSchema, &'a mut Vec<Counter>)> {
        match entity {
            EntityRef::Character { player, slot } => {
                let definition_id = self.character(player, slot)?.definition.clone();
                let schema = &rules
                    .character(&definition_id)
                    .expect("state references a loaded character")
                    .counters;
                let character = self.character_mut(player, slot)?;
                Ok((schema, &mut character.counters))
            }
            EntityRef::Modifier { instance, .. } => {
                let location = self
                    .find_modifier(instance)
                    .map(|(location, _)| location)
                    .ok_or_else(|| {
                        EngineError::Rule(format!("modifier instance {instance} is not active"))
                    })?;
                let definition_id = self.modifier_at(location).definition.clone();
                let schema = &rules
                    .modifier(&definition_id)
                    .expect("state references a loaded modifier")
                    .counters;
                Ok((schema, &mut self.modifier_at_mut(location).counters))
            }
        }
    }

    pub(crate) fn modifier_list_mut(
        &mut self,
        player: PlayerId,
        zone: Zone,
        host: usize,
    ) -> Result<&mut Vec<ModifierState>> {
        let player_state = &mut self.players[player];
        match zone {
            Zone::Character => player_state
                .characters
                .get_mut(host)
                .map(|character| &mut character.modifiers)
                .ok_or_else(|| {
                    EngineError::Rule(format!("character {player}:{host} does not exist"))
                }),
            Zone::Combat => Ok(&mut player_state.combat),
            Zone::Summon => Ok(&mut player_state.summons),
            Zone::Support => Ok(&mut player_state.supports),
        }
    }

    pub(crate) fn find_modifier(
        &self,
        instance: InstanceId,
    ) -> Option<(ModifierLocation, &ModifierState)> {
        for (player, player_state) in self.players.iter().enumerate() {
            for (slot, character) in player_state.characters.iter().enumerate() {
                if let Some((index, modifier)) = character
                    .modifiers
                    .iter()
                    .enumerate()
                    .find(|(_, modifier)| modifier.instance == instance)
                {
                    return Some((
                        ModifierLocation {
                            player,
                            zone: Zone::Character,
                            host: slot,
                            index,
                        },
                        modifier,
                    ));
                }
            }
            for (zone, modifiers) in [
                (Zone::Combat, &player_state.combat),
                (Zone::Summon, &player_state.summons),
                (Zone::Support, &player_state.supports),
            ] {
                if let Some((index, modifier)) = modifiers
                    .iter()
                    .enumerate()
                    .find(|(_, modifier)| modifier.instance == instance)
                {
                    return Some((
                        ModifierLocation {
                            player,
                            zone,
                            host: 0,
                            index,
                        },
                        modifier,
                    ));
                }
            }
        }
        None
    }

    pub(crate) fn character_entity(&self, player: PlayerId, definition: &str) -> Option<EntityRef> {
        self.players[player]
            .characters
            .iter()
            .position(|character| character.definition == definition)
            .map(|slot| EntityRef::Character { player, slot })
    }

    pub(crate) fn modifier_entity(&self, player: PlayerId, definition: &str) -> Option<EntityRef> {
        let state = &self.players[player];
        state
            .characters
            .iter()
            .flat_map(|character| &character.modifiers)
            .chain(&state.combat)
            .chain(&state.summons)
            .chain(&state.supports)
            .find(|modifier| modifier.definition == definition)
            .map(|modifier| EntityRef::Modifier {
                player,
                instance: modifier.instance,
            })
    }

    pub(crate) fn character_modifier_entity(
        &self,
        player: PlayerId,
        slot: usize,
        definition: &str,
    ) -> Option<EntityRef> {
        self.players[player].characters[slot]
            .modifiers
            .iter()
            .find(|modifier| modifier.definition == definition)
            .map(|modifier| EntityRef::Modifier {
                player,
                instance: modifier.instance,
            })
    }

    pub(crate) fn modifier_at(&self, location: ModifierLocation) -> &ModifierState {
        match location.zone {
            Zone::Character => {
                &self.players[location.player].characters[location.host].modifiers[location.index]
            }
            Zone::Combat => &self.players[location.player].combat[location.index],
            Zone::Summon => &self.players[location.player].summons[location.index],
            Zone::Support => &self.players[location.player].supports[location.index],
        }
    }

    pub(crate) fn modifier_at_mut(&mut self, location: ModifierLocation) -> &mut ModifierState {
        match location.zone {
            Zone::Character => {
                &mut self.players[location.player].characters[location.host].modifiers
                    [location.index]
            }
            Zone::Combat => &mut self.players[location.player].combat[location.index],
            Zone::Summon => &mut self.players[location.player].summons[location.index],
            Zone::Support => &mut self.players[location.player].supports[location.index],
        }
    }
}

fn initial_phase(players: &[PlayerConfig; 2]) -> Result<Phase> {
    match (players[0].active, players[1].active) {
        (None, None) => Ok(Phase::SelectActive),
        (Some(_), Some(_)) => Ok(Phase::Redraw),
        _ => Err(EngineError::InvalidGame(
            "both players must either select or preselect active characters".to_owned(),
        )),
    }
}

fn build_player(rules: &Ruleset, player: PlayerId, config: PlayerConfig) -> Result<PlayerState> {
    if config.characters.is_empty() {
        return Err(EngineError::InvalidGame(format!(
            "player {player} has no characters"
        )));
    }
    let active = config.active.unwrap_or(0);
    if active >= config.characters.len() {
        return Err(EngineError::InvalidGame(format!(
            "player {player} active slot {active} is invalid"
        )));
    }
    let characters = config
        .characters
        .into_iter()
        .map(|id| build_character(rules, player, &id))
        .collect::<Result<Vec<_>>>()?;
    let deck = config
        .deck
        .into_iter()
        .map(|id| validate_card(rules, player, &id))
        .collect::<Result<Vec<_>>>()?;
    Ok(PlayerState {
        characters,
        active,
        dice: config.dice,
        deck,
        ..PlayerState::default()
    })
}

fn build_character(rules: &Ruleset, player: PlayerId, id: &str) -> Result<CharacterState> {
    let definition = rules.character(id).ok_or_else(|| {
        EngineError::InvalidGame(format!("player {player} character {id:?} is not defined"))
    })?;
    Ok(CharacterState {
        definition: definition.id.clone(),
        counters: definition.counters.initial_values(),
        auras: Vec::new(),
        satiated: false,
        modifiers: Vec::new(),
    })
}

fn validate_card(rules: &Ruleset, player: PlayerId, id: &str) -> Result<String> {
    rules.card(id).map(|card| card.id.clone()).ok_or_else(|| {
        EngineError::InvalidGame(format!("player {player} card {id:?} is not defined"))
    })
}
