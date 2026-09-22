use crate::{
    Counter, CounterSchema, DiceSet, EngineError, EntityRef, InstanceId, PlayerId, Result, Ruleset,
    Zone,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Redraw,
    Roll,
    Action,
    Finished,
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
    pub decision: Option<Decision>,
    pub players: [PlayerState; 2],
    pub next_instance: InstanceId,
    pub next_decision: crate::DecisionId,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct PlayerState {
    pub characters: Vec<CharacterState>,
    pub active: usize,
    pub dice: DiceSet,
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
    pub modifiers: Vec<ModifierState>,
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
    pub active: usize,
    pub dice: DiceSet,
}

#[derive(Clone, Debug)]
pub struct GameConfig {
    pub players: [PlayerConfig; 2],
    pub first: PlayerId,
    pub seed: u64,
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
        let mut players = [PlayerState::default(), PlayerState::default()];
        for (player_id, player_config) in config.players.into_iter().enumerate() {
            if player_config.characters.is_empty() {
                return Err(EngineError::InvalidGame(format!(
                    "player {player_id} has no characters"
                )));
            }
            if player_config.active >= player_config.characters.len() {
                return Err(EngineError::InvalidGame(format!(
                    "player {player_id} active slot {} is invalid",
                    player_config.active
                )));
            }
            let mut characters = Vec::with_capacity(player_config.characters.len());
            for character_id in player_config.characters {
                let definition = rules.character(&character_id).ok_or_else(|| {
                    EngineError::InvalidGame(format!(
                        "player {player_id} character {character_id:?} is not defined"
                    ))
                })?;
                characters.push(CharacterState {
                    definition: definition.id.clone(),
                    counters: definition.counters.initial_values(),
                    modifiers: Vec::new(),
                });
            }
            let deck = player_config
                .deck
                .into_iter()
                .map(|card_id| {
                    rules
                        .card(&card_id)
                        .map(|card| card.id.clone())
                        .ok_or_else(|| {
                            EngineError::InvalidGame(format!(
                                "player {player_id} card {card_id:?} is not defined"
                            ))
                        })
                })
                .collect::<Result<Vec<_>>>()?;
            players[player_id] = PlayerState {
                characters,
                active: player_config.active,
                dice: player_config.dice,
                deck,
                ..PlayerState::default()
            };
        }
        Ok(Self {
            round: 1,
            phase: Phase::Redraw,
            turn: config.first,
            winner: None,
            decision: None,
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
