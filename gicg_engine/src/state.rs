use crate::{
    Counter, CounterSchema, DefinitionId, DiceSet, EngineError, EntityRef, InstanceId, PlayerId,
    Result, Ruleset, Zone,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Phase {
    Redraw,
    Roll,
    Action,
    Finished,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionKind {
    Choice,
    ForcedSwitch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChoiceOption {
    pub id: String,
    pub label: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Decision {
    pub id: crate::DecisionId,
    pub kind: DecisionKind,
    pub player: PlayerId,
    pub options: Vec<ChoiceOption>,
}

#[derive(Clone, Debug)]
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

#[derive(Clone, Debug, Default)]
pub struct PlayerState {
    pub counters: Vec<Counter>,
    pub characters: Vec<CharacterState>,
    pub active: u8,
    pub dice: DiceSet,
    pub deck: Vec<DefinitionId>,
    pub hand: Vec<DefinitionId>,
    pub discard: Vec<DefinitionId>,
    pub ended: bool,
    pub combat: Vec<ModifierState>,
    pub summons: Vec<ModifierState>,
    pub supports: Vec<ModifierState>,
}

#[derive(Clone, Debug)]
pub struct CharacterState {
    pub definition: DefinitionId,
    pub counters: Vec<Counter>,
    pub auras: u16,
    pub modifiers: Vec<ModifierState>,
}

#[derive(Clone, Debug)]
pub struct ModifierState {
    pub instance: InstanceId,
    pub definition: DefinitionId,
    pub counters: Vec<Counter>,
}

#[derive(Clone, Debug)]
pub struct PlayerConfig {
    pub characters: Vec<String>,
    pub deck: Vec<String>,
    pub active: u8,
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
    pub host: u8,
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
            if usize::from(player_config.active) >= player_config.characters.len() {
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
                    definition: definition.definition,
                    counters: definition.counters.initial_values(),
                    auras: 0,
                    modifiers: Vec::new(),
                });
            }
            let deck = player_config
                .deck
                .into_iter()
                .map(|card_id| {
                    rules
                        .card(&card_id)
                        .map(|card| card.definition)
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
            slot: self.players[usize::from(player)].active,
        }
    }

    pub fn character(&self, player: PlayerId, slot: u8) -> Result<&CharacterState> {
        self.players
            .get(usize::from(player))
            .and_then(|state| state.characters.get(usize::from(slot)))
            .ok_or_else(|| {
                EngineError::InvalidCommand(format!("character {player}:{slot} does not exist"))
            })
    }

    pub(crate) fn character_mut(
        &mut self,
        player: PlayerId,
        slot: u8,
    ) -> Result<&mut CharacterState> {
        self.players
            .get_mut(usize::from(player))
            .and_then(|state| state.characters.get_mut(usize::from(slot)))
            .ok_or_else(|| {
                EngineError::InvalidCommand(format!("character {player}:{slot} does not exist"))
            })
    }

    pub fn counter(&self, rules: &Ruleset, entity: EntityRef, name: &str) -> Result<Counter> {
        let (schema, values) = self.entity_counters(rules, entity)?;
        let field = schema.field(name).ok_or_else(|| {
            EngineError::Rule(format!("entity {entity:?} has no counter {name:?}"))
        })?;
        Ok(values[usize::from(field)])
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
        values[usize::from(field)] = value;
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
                    .character_definition(character.definition)
                    .ok_or_else(|| {
                        EngineError::Rule(format!(
                            "character definition {} is missing",
                            character.definition
                        ))
                    })?;
                Ok((&definition.counters, &character.counters))
            }
            EntityRef::Modifier { instance, .. } => {
                let (_, modifier) = self.find_modifier(instance).ok_or_else(|| {
                    EngineError::Rule(format!("modifier instance {instance} is not active"))
                })?;
                let definition =
                    rules
                        .modifier_definition(modifier.definition)
                        .ok_or_else(|| {
                            EngineError::Rule(format!(
                                "modifier definition {} is missing",
                                modifier.definition
                            ))
                        })?;
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
                let definition_id = self.character(player, slot)?.definition;
                let schema = &rules
                    .character_definition(definition_id)
                    .ok_or_else(|| {
                        EngineError::Rule(format!(
                            "character definition {definition_id} is missing"
                        ))
                    })?
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
                let definition_id = self.modifier_at(location).definition;
                let schema = &rules
                    .modifier_definition(definition_id)
                    .ok_or_else(|| {
                        EngineError::Rule(format!("modifier definition {definition_id} is missing"))
                    })?
                    .counters;
                Ok((schema, &mut self.modifier_at_mut(location).counters))
            }
        }
    }

    pub(crate) fn modifier_list_mut(
        &mut self,
        player: PlayerId,
        zone: Zone,
        host: u8,
    ) -> Result<&mut Vec<ModifierState>> {
        let player_state = self
            .players
            .get_mut(usize::from(player))
            .ok_or_else(|| EngineError::Rule(format!("player {player} is invalid")))?;
        match zone {
            Zone::Character => player_state
                .characters
                .get_mut(usize::from(host))
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
                            player: player as PlayerId,
                            zone: Zone::Character,
                            host: slot as u8,
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
                            player: player as PlayerId,
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

    pub(crate) fn modifier_at(&self, location: ModifierLocation) -> &ModifierState {
        match location.zone {
            Zone::Character => {
                &self.players[usize::from(location.player)].characters[usize::from(location.host)]
                    .modifiers[location.index]
            }
            Zone::Combat => &self.players[usize::from(location.player)].combat[location.index],
            Zone::Summon => &self.players[usize::from(location.player)].summons[location.index],
            Zone::Support => &self.players[usize::from(location.player)].supports[location.index],
        }
    }

    pub(crate) fn modifier_at_mut(&mut self, location: ModifierLocation) -> &mut ModifierState {
        match location.zone {
            Zone::Character => {
                &mut self.players[usize::from(location.player)].characters
                    [usize::from(location.host)]
                .modifiers[location.index]
            }
            Zone::Combat => &mut self.players[usize::from(location.player)].combat[location.index],
            Zone::Summon => &mut self.players[usize::from(location.player)].summons[location.index],
            Zone::Support => {
                &mut self.players[usize::from(location.player)].supports[location.index]
            }
        }
    }
}
