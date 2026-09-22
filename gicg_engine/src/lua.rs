use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};

use mlua::{Function, Lua, LuaOptions, LuaSerdeExt, RegistryKey, Scope, StdLib, Table, Value};
use sha2::{Digest, Sha256};

use crate::{
    ActionDefinition, ActionKind, ActionModifierDefinition, ActionTempo, ActionTraits,
    CardDefinition, CardKind, CardTargetDefinition, Cost, CounterConsume, CounterCost,
    CounterDefinition, CounterSchema, DamageDirection, DamageModifierDefinition,
    DeckRequirementDefinition, DiceSet, Effect, Element, EngineError, EntityRef, EventKind,
    GameState, HandlerId, MergePolicy, ModifierDefinition, Result, RuleContext, Ruleset, SkillKind,
    TalentDefinition, TargetRef, TargetSide, TargetState, Zone,
};

struct LoadState {
    characters: Vec<crate::CharacterDefinition>,
    modifiers: Vec<ModifierDefinition>,
    cards: Vec<CardDefinition>,
    handlers: HashMap<HandlerId, RegistryKey>,
    next_handler: HandlerId,
}

struct ParsedModifierRules {
    remove_at_zero: Option<usize>,
    damage: Option<DamageModifierDefinition>,
    action: Option<ActionModifierDefinition>,
    roll: Option<crate::RollModifierDefinition>,
    revive: Option<crate::ReviveModifierDefinition>,
}

impl LoadState {
    fn new() -> Self {
        Self {
            characters: Vec::new(),
            modifiers: Vec::new(),
            cards: Vec::new(),
            handlers: HashMap::new(),
            next_handler: 1,
        }
    }

    fn add_handler(
        &mut self,
        lua: &Lua,
        function: Function,
        label: &str,
    ) -> mlua::Result<HandlerId> {
        let info = function.info();
        if info.num_params != 1 || info.is_vararg {
            return Err(mlua::Error::runtime(format!(
                "{label} must accept exactly one context parameter"
            )));
        }
        if info.num_upvalues > 1 || (info.num_upvalues == 1 && function.environment().is_none()) {
            return Err(mlua::Error::runtime(format!(
                "{label} must not capture local state"
            )));
        }
        let id = self.next_handler;
        self.next_handler = self
            .next_handler
            .checked_add(1)
            .ok_or_else(|| mlua::Error::runtime("too many rule handlers"))?;
        self.handlers
            .insert(id, lua.create_registry_value(function)?);
        Ok(id)
    }
}

pub struct LuaRuntime {
    lua: Lua,
    rules: Ruleset,
    handlers: HashMap<HandlerId, RegistryKey>,
}

impl LuaRuntime {
    pub fn load(root: impl AsRef<Path>) -> Result<Self> {
        let root = fs::canonicalize(root)?;
        let files = lua_files(&root)?;
        require_lua_files(&root, &files)?;
        Self::load_files(&root, files)
    }

    fn load_files(root: &Path, files: Vec<PathBuf>) -> Result<Self> {
        let lua = Lua::new_with(
            StdLib::TABLE | StdLib::STRING | StdLib::MATH | StdLib::UTF8,
            LuaOptions::default(),
        )?;
        install_effect_constructors(&lua)?;
        lua.set_app_data(LoadState::new());
        install_definition_functions(&lua)?;
        let hash = execute_files(&lua, root, files)?;
        lock_runtime(&lua)?;
        let state: LoadState = lua.remove_app_data().ok_or_else(|| {
            EngineError::InvalidRuleset("ruleset loader lost its state".to_owned())
        })?;
        seal_handlers(&lua, &state.handlers)?;
        let rules = Ruleset::new(hash, state.characters, state.modifiers, state.cards)?;
        Ok(Self {
            lua,
            rules,
            handlers: state.handlers,
        })
    }

    pub fn rules(&self) -> &Ruleset {
        &self.rules
    }

    pub(crate) fn call(
        &self,
        handler: HandlerId,
        context: &RuleContext,
        state: &GameState,
    ) -> Result<Vec<Effect>> {
        let key = self
            .handlers
            .get(&handler)
            .ok_or_else(|| EngineError::Rule(format!("handler {handler} is not registered")))?;
        let function: Function = self.lua.registry_value(key)?;
        self.lua
            .scope(|scope| {
                let table = context_table(&self.lua, context)?;
                set_context_definitions(&table, state, context)?;
                install_counter_reader(scope, &table, state, &self.rules, context)?;
                let modifier_counter =
                    scope.create_function(|_, (definition, name): (String, String)| {
                        read_modifier_counter(state, &self.rules, context, &definition, &name)
                    })?;
                table.set("modifier_counter", modifier_counter)?;
                let value: Value = function.call(table)?;
                parse_effects(&self.lua, value).map_err(lua_error)
            })
            .map_err(EngineError::from)
    }
}

fn set_context_definitions(
    table: &Table,
    state: &GameState,
    context: &RuleContext,
) -> mlua::Result<()> {
    set_entity_definition(table, "actor_definition", state, context.actor)?;
    set_entity_definition(table, "source_definition", state, context.source)?;
    set_entity_definition(table, "target_definition", state, context.target)
}

fn set_entity_definition(
    table: &Table,
    field: &str,
    state: &GameState,
    entity: Option<EntityRef>,
) -> mlua::Result<()> {
    let definition = match entity {
        Some(EntityRef::Character { player, slot }) => Some(
            state
                .character(player, slot)
                .map_err(lua_error)?
                .definition
                .as_str(),
        ),
        Some(EntityRef::Modifier { instance, .. }) => state
            .find_modifier(instance)
            .map(|(_, modifier)| modifier.definition.as_str()),
        None => None,
    };
    table.set(field, definition)
}

fn install_counter_reader<'scope, 'env: 'scope>(
    scope: &'scope Scope<'scope, 'env>,
    table: &Table,
    state: &'env GameState,
    rules: &'env Ruleset,
    context: &'env RuleContext,
) -> mlua::Result<()> {
    let counter = scope.create_function(|_, (target, name): (String, String)| {
        read_counter(state, rules, context, &target, &name)
    })?;
    table.set("counter", counter)
}

fn require_lua_files(root: &Path, files: &[PathBuf]) -> Result<()> {
    if files.is_empty() {
        return Err(EngineError::InvalidRuleset(format!(
            "{} contains no Lua files",
            root.display()
        )));
    }
    Ok(())
}

fn execute_files(lua: &Lua, root: &Path, files: Vec<PathBuf>) -> Result<String> {
    let mut digest = Sha256::new();
    for path in files {
        execute_file(lua, root, &path, &mut digest)?;
    }
    Ok(digest
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn execute_file(lua: &Lua, root: &Path, path: &Path, digest: &mut Sha256) -> Result<()> {
    let relative = path
        .strip_prefix(root)
        .map_err(|error| EngineError::InvalidRuleset(format!("resolve ruleset path: {error}")))?;
    let source = fs::read(path)?;
    digest.update(relative.to_string_lossy().as_bytes());
    digest.update([0]);
    digest.update(&source);
    digest.update([0]);
    let source = std::str::from_utf8(&source).map_err(|error| {
        EngineError::InvalidRuleset(format!("{} is not UTF-8: {error}", path.display()))
    })?;
    lua.load(source)
        .set_name(relative.to_string_lossy())
        .exec()
        .map_err(|error| {
            EngineError::InvalidRuleset(format!("load {}: {error}", relative.display()))
        })
}

fn lock_runtime(lua: &Lua) -> Result<()> {
    for name in [
        "character",
        "modifier",
        "card",
        "_G",
        "load",
        "dofile",
        "loadfile",
        "collectgarbage",
    ] {
        lua.globals().set(name, Value::Nil)?;
    }
    lua.gc_collect().map_err(EngineError::from)
}

fn read_counter(
    state: &GameState,
    rules: &Ruleset,
    context: &RuleContext,
    target: &str,
    name: &str,
) -> mlua::Result<i32> {
    let target =
        TargetRef::parse(target).ok_or_else(|| mlua::Error::runtime("unknown counter target"))?;
    let entity = resolve_target(state, context, target).map_err(lua_error)?;
    state.counter(rules, entity, name).map_err(lua_error)
}

fn read_modifier_counter(
    state: &GameState,
    rules: &Ruleset,
    context: &RuleContext,
    definition: &str,
    name: &str,
) -> mlua::Result<i32> {
    let player = context
        .source
        .or(context.actor)
        .map(EntityRef::player)
        .ok_or_else(|| mlua::Error::runtime("context has no owner"))?;
    let Some(entity) = state.modifier_entity(player, definition) else {
        return Ok(0);
    };
    state.counter(rules, entity, name).map_err(lua_error)
}

fn lua_files(root: &Path) -> Result<Vec<PathBuf>> {
    fn visit(path: &Path, files: &mut Vec<PathBuf>) -> std::io::Result<()> {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                visit(&path, files)?;
            } else if path.extension().is_some_and(|extension| extension == "lua") {
                files.push(path);
            }
        }
        Ok(())
    }
    let mut files = Vec::new();
    visit(root, &mut files)?;
    files.sort_unstable();
    Ok(files)
}

fn install_effect_constructors(lua: &Lua) -> mlua::Result<()> {
    lua.load(
        r#"
        function add_counter(target, name, delta)
            return { kind = "add_counter", target = target, name = name, delta = delta }
        end
        function damage(target, element, amount)
            return { kind = "damage", target = target, element = element, amount = amount }
        end
        function piercing(side, amount)
            return { kind = "piercing", side = side, amount = amount }
        end
        function heal(target, amount)
            return { kind = "heal", target = target, amount = amount }
        end
        function revive(target, amount)
            return { kind = "revive", target = target, amount = amount }
        end
        function add_modifier(target, definition)
            return { kind = "add_modifier", target = target, definition = definition }
        end
        function add_modifier_counter(definition, name, delta)
            return { kind = "add_modifier_counter", definition = definition, name = name, delta = delta }
        end
        function add_character_counter(character, name, delta)
            return { kind = "add_character_counter", character = character, name = name, delta = delta }
        end
        function remove_modifier(definition)
            return { kind = "remove_modifier", definition = definition }
        end
        function remove_target(target)
            return { kind = "remove_target", target = target }
        end
        function add_card(card)
            return { kind = "add_card", card = card }
        end
        function add_dice(die, count)
            return { kind = "add_dice", die = die, count = count }
        end
        function convert_dice(die)
            return { kind = "convert_dice", die = die }
        end
        function switch_active(side)
            return { kind = "switch_active", side = side }
        end
        function draw(count)
            return { kind = "draw", count = count }
        end
        function discard(side, count)
            return { kind = "discard", side = side, count = count }
        end
        function draw_card(card)
            return { kind = "draw_card", card = card }
        end
        function recover_card(card)
            return { kind = "recover_card", card = card }
        end
        function add_deck_card(card, count)
            return { kind = "add_deck_card", card = card, count = count }
        end
        function choose(continuation, options)
            return { kind = "choice", continuation = continuation, options = options }
        end
        "#,
    )
    .exec()
}

fn install_definition_functions(lua: &Lua) -> mlua::Result<()> {
    lua.globals().set(
        "character",
        lua.create_function(|lua, table: Table| {
            let mut state = lua.app_data_mut::<LoadState>().expect("load state exists");
            let definition = parse_character(lua, &mut state, table)?;
            state.characters.push(definition);
            Ok(())
        })?,
    )?;
    lua.globals().set(
        "modifier",
        lua.create_function(|lua, table: Table| {
            let mut state = lua.app_data_mut::<LoadState>().expect("load state exists");
            let definition = parse_modifier(lua, &mut state, table)?;
            state.modifiers.push(definition);
            Ok(())
        })?,
    )?;
    lua.globals().set(
        "card",
        lua.create_function(|lua, table: Table| {
            let mut state = lua.app_data_mut::<LoadState>().expect("load state exists");
            let definition = parse_card(lua, &mut state, table)?;
            state.cards.push(definition);
            Ok(())
        })?,
    )?;
    Ok(())
}

fn parse_card(lua: &Lua, state: &mut LoadState, table: Table) -> mlua::Result<CardDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let description = required_string(&table, "description")?;
    let (kind, target, talent, tempo, cost) = parse_card_properties(&table)?;
    let resolve = add_table_handler(lua, state, &table, "resolve", &format!("card {id} resolve"))?;
    let continuations = parse_continuations(lua, state, &table, &format!("card {id}"))?;
    Ok(CardDefinition {
        id: id.clone(),
        name: name.clone(),
        description,
        kind,
        deck_requirements: parse_deck_requirements(&table)?,
        target,
        talent,
        action: ActionDefinition {
            id,
            name,
            skill: None,
            tempo,
            cost,
            resolve,
            continuations,
        },
    })
}

fn parse_deck_requirements(table: &Table) -> mlua::Result<Vec<DeckRequirementDefinition>> {
    let Some(deck) = table.get::<Option<Table>>("deck")? else {
        return Ok(Vec::new());
    };
    let Some(tags) = deck.get::<Option<Table>>("tags")? else {
        return Ok(Vec::new());
    };
    tags.pairs::<String, usize>()
        .map(|entry| {
            let (tag, count) = entry?;
            Ok(DeckRequirementDefinition { tag, count })
        })
        .collect()
}

type CardProperties = (
    CardKind,
    Option<CardTargetDefinition>,
    Option<TalentDefinition>,
    ActionTempo,
    Cost,
);

fn parse_card_properties(table: &Table) -> mlua::Result<CardProperties> {
    Ok((
        parse_card_kind(table)?,
        parse_card_target(table)?,
        parse_talent(table)?,
        parse_tempo(table, "fast")?,
        parse_optional_cost(table, &CounterSchema::default())?,
    ))
}

fn parse_talent(table: &Table) -> mlua::Result<Option<TalentDefinition>> {
    let Some(talent) = table.get::<Option<Table>>("talent")? else {
        return Ok(None);
    };
    Ok(Some(TalentDefinition {
        character: required_string(&talent, "character")?,
        action: required_string(&talent, "action")?,
    }))
}

fn parse_card_kind(table: &Table) -> mlua::Result<CardKind> {
    let value = table.get::<Option<String>>("kind")?;
    CardKind::parse(value.as_deref().unwrap_or("event")).map_err(lua_error)
}

fn parse_card_target(table: &Table) -> mlua::Result<Option<CardTargetDefinition>> {
    let Some(target) = table.get::<Option<Table>>("target")? else {
        return Ok(None);
    };
    parse_card_target_table(&target).map(Some)
}

fn parse_card_target_table(target: &Table) -> mlua::Result<CardTargetDefinition> {
    let side = target.get::<Option<String>>("side")?;
    let state = target.get::<Option<String>>("state")?;
    let kind = target.get::<Option<String>>("kind")?;
    Ok(CardTargetDefinition {
        zone: Zone::parse(kind.as_deref().unwrap_or("character")).map_err(lua_error)?,
        side: TargetSide::parse(side.as_deref().unwrap_or("own")).map_err(lua_error)?,
        state: TargetState::parse(state.as_deref().unwrap_or("alive")).map_err(lua_error)?,
        damaged: target.get::<Option<bool>>("damaged")?.unwrap_or(false),
        active_only: target.get::<Option<bool>>("active_only")?.unwrap_or(false),
        tags: parse_strings(target, "tags")?,
    })
}

fn parse_character(
    lua: &Lua,
    state: &mut LoadState,
    table: Table,
) -> mlua::Result<crate::CharacterDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let element = parse_element(&table)?;
    let counters = parse_counters(table.get("counters")?)?;
    require_hp(&id, &counters)?;
    let actions = parse_actions(lua, state, &table, &id, &counters)?;
    let passives = parse_strings(&table, "passives")?;
    let tags = parse_strings(&table, "tags")?;
    crate::CharacterDefinition::new(id, name, element, counters, actions, passives, tags)
        .map_err(lua_error)
}

fn parse_action(
    lua: &Lua,
    state: &mut LoadState,
    character_id: &str,
    table: Table,
    counters: &CounterSchema,
) -> mlua::Result<ActionDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let skill = SkillKind::parse(&required_string(&table, "kind")?).map_err(lua_error)?;
    let tempo = parse_tempo(&table, "combat")?;
    let cost = parse_optional_cost(&table, counters)?;
    let label = format!("action {character_id}.{id} resolve");
    let resolve = add_table_handler(lua, state, &table, "resolve", &label)?;
    let continuations =
        parse_continuations(lua, state, &table, &format!("action {character_id}.{id}"))?;
    Ok(ActionDefinition {
        id,
        name,
        skill: Some(skill),
        tempo,
        cost,
        resolve,
        continuations,
    })
}

fn parse_modifier(
    lua: &Lua,
    state: &mut LoadState,
    table: Table,
) -> mlua::Result<ModifierDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let zone = parse_zone(&table)?;
    let slot = parse_modifier_slot(&table, zone, &id)?;
    let merge = parse_merge(&table)?;
    let counters = parse_counters(table.get("counters")?)?;
    let rules = parse_modifier_rules(&table, &id, &counters)?;
    let handlers = parse_handlers(lua, state, &table, &id)?;
    Ok(ModifierDefinition {
        id,
        name,
        zone,
        slot,
        counters,
        merge,
        remove_at_zero: rules.remove_at_zero,
        damage: rules.damage,
        action: rules.action,
        roll: rules.roll,
        revive: rules.revive,
        handlers,
    })
}

fn parse_roll_modifier(
    table: &Table,
    modifier_id: &str,
) -> mlua::Result<Option<crate::RollModifierDefinition>> {
    let Some(roll) = table.get::<Option<Table>>("roll")? else {
        return Ok(None);
    };
    let rerolls = roll.get::<Option<u8>>("rerolls")?.unwrap_or(0);
    let fixed = parse_dice_set(&roll, "fixed")?;
    if rerolls == 0 && fixed.total() == 0 {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} roll rule has no effect"
        )));
    }
    if fixed.total() > 8 {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} fixes more than 8 dice"
        )));
    }
    Ok(Some(crate::RollModifierDefinition { rerolls, fixed }))
}

fn parse_dice_set(table: &Table, field: &str) -> mlua::Result<DiceSet> {
    let mut dice = DiceSet::default();
    let Some(values) = table.get::<Option<Table>>(field)? else {
        return Ok(dice);
    };
    for entry in values.pairs::<String, u8>() {
        let (name, count) = entry?;
        dice.set(crate::Die::parse(&name).map_err(lua_error)?, count);
    }
    Ok(dice)
}

fn parse_modifier_slot(
    table: &Table,
    zone: Zone,
    modifier_id: &str,
) -> mlua::Result<Option<String>> {
    let slot = table.get::<Option<String>>("slot")?;
    if slot.as_deref().is_some_and(str::is_empty) {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} slot must not be empty"
        )));
    }
    if slot.is_some() && zone != Zone::Character {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} slot requires character zone"
        )));
    }
    Ok(slot)
}

fn parse_modifier_rules(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<ParsedModifierRules> {
    Ok(ParsedModifierRules {
        remove_at_zero: parse_remove_at_zero(table, modifier_id, counters)?,
        damage: parse_damage_modifier(table, modifier_id, counters)?,
        action: parse_action_modifier(table, modifier_id, counters)?,
        roll: parse_roll_modifier(table, modifier_id)?,
        revive: parse_revive_modifier(table, modifier_id, counters)?,
    })
}

fn parse_revive_modifier(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Option<crate::ReviveModifierDefinition>> {
    let Some(revive) = table.get::<Option<Table>>("revive")? else {
        return Ok(None);
    };
    let hp = revive.get::<i32>("hp")?;
    if hp <= 0 {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} revive hp must be positive"
        )));
    }
    let counter = required_string(&revive, "counter")?;
    if counters.field(&counter).is_none() {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} revive refers to unknown counter {counter:?}"
        )));
    }
    let consume = parse_modifier_consume(&revive, modifier_id, "revive")?;
    validate_modifier_consumption(
        &Some(counter.clone()),
        counters,
        consume,
        modifier_id,
        "revive",
    )?;
    Ok(Some(crate::ReviveModifierDefinition {
        hp,
        counter,
        consume,
    }))
}

fn parse_action_modifier(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Option<ActionModifierDefinition>> {
    let Some(action) = table.get::<Option<Table>>("action")? else {
        return Ok(None);
    };
    parse_action_modifier_table(action, modifier_id, counters).map(Some)
}

fn parse_action_modifier_table(
    table: Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<ActionModifierDefinition> {
    let (kinds, skills, actions) = parse_action_filters(&table)?;
    let (reduce_dice, tempo, forbid) = parse_action_changes(&table, modifier_id)?;
    let counter = parse_counter_name(&table, "counter", modifier_id, counters, "action")?;
    let consume = parse_modifier_consume(&table, modifier_id, "action")?;
    validate_modifier_consumption(&counter, counters, consume, modifier_id, "action")?;
    Ok(ActionModifierDefinition {
        kinds,
        skills,
        actions,
        reduce_dice,
        tempo,
        counter,
        consume,
        traits: parse_action_traits(&table)?,
        forbid,
    })
}

fn parse_action_filters(
    table: &Table,
) -> mlua::Result<(Vec<ActionKind>, Vec<SkillKind>, Vec<String>)> {
    Ok((
        parse_action_kinds(table)?,
        parse_skill_kinds(table)?,
        parse_strings(table, "actions")?,
    ))
}

fn parse_action_changes(
    table: &Table,
    modifier_id: &str,
) -> mlua::Result<(u8, Option<ActionTempo>, bool)> {
    let reduce_dice = table.get::<Option<u8>>("reduce_dice")?.unwrap_or(0);
    let forbid = table.get::<Option<bool>>("forbid")?.unwrap_or(false);
    let tempo = table
        .get::<Option<String>>("tempo")?
        .map(|value| ActionTempo::parse(&value).map_err(lua_error))
        .transpose()?;
    if reduce_dice == 0 && tempo.is_none() && !forbid {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} action rule has no effect"
        )));
    }
    Ok((reduce_dice, tempo, forbid))
}

fn parse_action_kinds(table: &Table) -> mlua::Result<Vec<ActionKind>> {
    parse_strings(table, "kinds")?
        .into_iter()
        .map(|value| ActionKind::parse(&value).map_err(lua_error))
        .collect()
}

fn parse_skill_kinds(table: &Table) -> mlua::Result<Vec<SkillKind>> {
    parse_strings(table, "skills")?
        .into_iter()
        .map(|value| SkillKind::parse(&value).map_err(lua_error))
        .collect()
}

fn parse_strings(table: &Table, field: &str) -> mlua::Result<Vec<String>> {
    let Some(values) = table.get::<Option<Table>>(field)? else {
        return Ok(Vec::new());
    };
    values.sequence_values::<String>().collect()
}

fn parse_damage_modifier(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Option<DamageModifierDefinition>> {
    let Some(damage) = table.get::<Option<Table>>("damage")? else {
        return Ok(None);
    };
    let definition = parse_damage_modifier_table(&damage, modifier_id, counters)?;
    validate_modifier_consumption(
        &definition.counter,
        counters,
        definition.consume,
        modifier_id,
        "damage",
    )?;
    Ok(Some(definition))
}

fn parse_damage_modifier_table(
    damage: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<DamageModifierDefinition> {
    let direction = parse_damage_direction(damage)?;
    let elements = parse_elements(damage)?;
    let (counter, shield) = parse_damage_counters(damage, modifier_id, counters)?;
    let consume = parse_damage_consume(damage, modifier_id)?;
    Ok(DamageModifierDefinition {
        direction,
        elements,
        delta: damage.get::<Option<i32>>("delta")?.unwrap_or(0),
        set_element: parse_optional_element(damage, "set_element")?,
        counter,
        consume,
        shield,
        active_only: damage.get::<Option<bool>>("active_only")?.unwrap_or(false),
        include_piercing: damage
            .get::<Option<bool>>("include_piercing")?
            .unwrap_or(false),
        traits: parse_action_traits(damage)?,
    })
}

fn parse_action_traits(table: &Table) -> mlua::Result<ActionTraits> {
    Ok(ActionTraits {
        charged: table.get::<Option<bool>>("charged")?.unwrap_or(false),
        plunging: table.get::<Option<bool>>("plunging")?.unwrap_or(false),
    })
}

fn parse_damage_direction(table: &Table) -> mlua::Result<DamageDirection> {
    match required_string(table, "direction")?.as_str() {
        "outgoing" => Ok(DamageDirection::Outgoing),
        "incoming" => Ok(DamageDirection::Incoming),
        value => Err(mlua::Error::runtime(format!(
            "unknown damage direction {value:?}"
        ))),
    }
}

fn parse_damage_counters(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<(Option<String>, Option<String>)> {
    let counter = parse_counter_name(table, "counter", modifier_id, counters, "damage")?;
    let shield = parse_counter_name(table, "shield", modifier_id, counters, "damage")?;
    if counter.is_some() && shield.is_some() {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} damage rule cannot define both counter and shield"
        )));
    }
    Ok((counter, shield))
}

fn parse_damage_consume(table: &Table, modifier_id: &str) -> mlua::Result<i32> {
    parse_modifier_consume(table, modifier_id, "damage")
}

fn parse_modifier_consume(table: &Table, modifier_id: &str, rule: &str) -> mlua::Result<i32> {
    let consume = table.get::<Option<i32>>("consume")?.unwrap_or(1);
    if consume <= 0 {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} {rule} consume must be positive"
        )));
    }
    Ok(consume)
}

fn validate_modifier_consumption(
    counter: &Option<String>,
    counters: &CounterSchema,
    consume: i32,
    modifier_id: &str,
    rule: &str,
) -> mlua::Result<()> {
    let Some(counter) = counter else {
        return Ok(());
    };
    let field = counters.field(counter).expect("modifier counter exists");
    let maximum = counters
        .definition(field)
        .expect("counter field exists")
        .max;
    if consume > maximum {
        return Err(mlua::Error::runtime(format!(
            "modifier {modifier_id:?} {rule} consumes more than counter {counter:?} can hold"
        )));
    }
    Ok(())
}

fn parse_optional_element(table: &Table, field: &str) -> mlua::Result<Option<Element>> {
    table
        .get::<Option<String>>(field)?
        .map(|value| Element::parse(&value).map_err(lua_error))
        .transpose()
}

fn parse_elements(table: &Table) -> mlua::Result<Vec<Element>> {
    let Some(elements) = table.get::<Option<Table>>("elements")? else {
        return Ok(Vec::new());
    };
    elements
        .sequence_values::<String>()
        .map(|value| Element::parse(&value?).map_err(lua_error))
        .collect()
}

fn parse_counter_name(
    table: &Table,
    field: &str,
    modifier_id: &str,
    counters: &CounterSchema,
    rule: &str,
) -> mlua::Result<Option<String>> {
    table
        .get::<Option<String>>(field)?
        .map(|name| {
            counters.field(&name).ok_or_else(|| {
                mlua::Error::runtime(format!(
                    "modifier {modifier_id:?} {rule} {field} counter {name:?} does not exist"
                ))
            })?;
            Ok(name)
        })
        .transpose()
}

fn parse_tempo(table: &Table, default: &str) -> mlua::Result<ActionTempo> {
    let value = table.get::<Option<String>>("tempo")?;
    ActionTempo::parse(value.as_deref().unwrap_or(default)).map_err(lua_error)
}

fn parse_optional_cost(table: &Table, counters: &CounterSchema) -> mlua::Result<Cost> {
    match table.get::<Option<Table>>("cost")? {
        Some(value) => parse_cost(value, counters),
        None => Ok(Cost::default()),
    }
}

fn add_table_handler(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    field: &str,
    label: &str,
) -> mlua::Result<HandlerId> {
    state.add_handler(lua, table.get(field)?, label)
}

fn parse_element(table: &Table) -> mlua::Result<Element> {
    Element::parse(&required_string(table, "element")?).map_err(lua_error)
}

fn require_hp(character_id: &str, counters: &CounterSchema) -> mlua::Result<()> {
    if counters.field("hp").is_none() {
        return Err(mlua::Error::runtime(format!(
            "character {character_id:?} has no hp counter"
        )));
    }
    Ok(())
}

fn parse_actions(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    character_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Vec<ActionDefinition>> {
    let mut actions = Vec::new();
    for action in table.get::<Table>("actions")?.sequence_values::<Table>() {
        actions.push(parse_action(lua, state, character_id, action?, counters)?);
    }
    if actions.is_empty() {
        return Err(mlua::Error::runtime(format!(
            "character {character_id:?} has no actions"
        )));
    }
    Ok(actions)
}

fn parse_continuations(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    owner: &str,
) -> mlua::Result<HashMap<String, HandlerId>> {
    let mut continuations = HashMap::new();
    let Some(entries) = table.get::<Option<Table>>("continue")? else {
        return Ok(continuations);
    };
    for entry in entries.pairs::<String, Function>() {
        let (name, function) = entry?;
        let label = format!("{owner} continuation {name}");
        continuations.insert(name, state.add_handler(lua, function, &label)?);
    }
    Ok(continuations)
}

fn parse_zone(table: &Table) -> mlua::Result<Zone> {
    let value = table.get::<Option<String>>("zone")?;
    Zone::parse(value.as_deref().unwrap_or("character")).map_err(lua_error)
}

fn parse_merge(table: &Table) -> mlua::Result<MergePolicy> {
    let value = table.get::<Option<String>>("merge")?;
    MergePolicy::parse(value.as_deref().unwrap_or("replace")).map_err(lua_error)
}

fn parse_remove_at_zero(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Option<usize>> {
    table
        .get::<Option<String>>("remove_at_zero")?
        .map(|name| {
            counters.field(&name).ok_or_else(|| {
                mlua::Error::runtime(format!(
                    "modifier {modifier_id:?} remove_at_zero counter {name:?} does not exist"
                ))
            })
        })
        .transpose()
}

fn parse_handlers(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    modifier_id: &str,
) -> mlua::Result<HashMap<EventKind, HandlerId>> {
    let mut handlers = HashMap::new();
    let Some(entries) = table.get::<Option<Table>>("handlers")? else {
        return Ok(handlers);
    };
    for entry in entries.pairs::<String, Function>() {
        let (event_name, function) = entry?;
        let event = EventKind::parse(&event_name).map_err(lua_error)?;
        let label = format!("modifier {modifier_id} handler {event_name}");
        let handler = state.add_handler(lua, function, &label)?;
        handlers.insert(event, handler);
    }
    Ok(handlers)
}

fn parse_counters(table: Table) -> mlua::Result<CounterSchema> {
    let mut counters = Vec::new();
    for entry in table.pairs::<String, Table>() {
        let (name, definition) = entry?;
        counters.push(CounterDefinition {
            name,
            initial: definition.get("initial")?,
            min: definition.get::<Option<i32>>("min")?.unwrap_or(0),
            max: definition.get::<Option<i32>>("max")?.unwrap_or(i32::MAX),
        });
    }
    CounterSchema::new(counters).map_err(lua_error)
}

fn parse_cost(table: Table, counters: &CounterSchema) -> mlua::Result<Cost> {
    let mut cost = Cost::default();
    parse_dice_cost(&table, &mut cost)?;
    parse_counter_costs(&table, counters, &mut cost)?;
    Ok(cost)
}

fn parse_dice_cost(table: &Table, cost: &mut Cost) -> mlua::Result<()> {
    let Some(dice) = table.get::<Option<Table>>("dice")? else {
        return Ok(());
    };
    for entry in dice.pairs::<String, u8>() {
        let (name, count) = entry?;
        match name.as_str() {
            "any" => cost.any = count,
            "same" => cost.same = count,
            _ => cost.dice.set(parse_specific_die(&name)?, count),
        }
    }
    Ok(())
}

fn parse_specific_die(name: &str) -> mlua::Result<crate::Die> {
    let die = crate::Die::parse(name).map_err(lua_error)?;
    if die == crate::Die::Omni {
        return Err(mlua::Error::runtime("omni cannot be a specific dice cost"));
    }
    Ok(die)
}

fn parse_counter_costs(
    table: &Table,
    counters: &CounterSchema,
    cost: &mut Cost,
) -> mlua::Result<()> {
    let Some(entries) = table.get::<Option<Table>>("counters")? else {
        return Ok(());
    };
    for entry in entries.sequence_values::<Table>() {
        let parsed = parse_counter_cost(entry?, counters)?;
        if cost
            .counters
            .iter()
            .any(|existing| existing.field == parsed.field)
        {
            return Err(mlua::Error::runtime("action cost repeats a counter field"));
        }
        cost.counters.push(parsed);
    }
    Ok(())
}

fn parse_counter_cost(entry: Table, counters: &CounterSchema) -> mlua::Result<CounterCost> {
    let name = required_string(&entry, "name")?;
    let field = counters.field(&name).ok_or_else(|| {
        mlua::Error::runtime(format!("counter cost refers to unknown counter {name:?}"))
    })?;
    let require = entry.get("require")?;
    let consume = parse_counter_consume(entry.get("consume")?, &name)?;
    let definition = counters.definition(field).expect("counter field exists");
    validate_counter_cost(&name, definition, require, consume)?;
    Ok(CounterCost {
        field,
        require,
        consume,
    })
}

fn validate_counter_cost(
    name: &str,
    definition: &CounterDefinition,
    require: i32,
    consume: CounterConsume,
) -> mlua::Result<()> {
    if !(definition.min..=definition.max).contains(&require) {
        return Err(mlua::Error::runtime(format!(
            "counter {name:?} requirement is outside its range"
        )));
    }
    let valid = match consume {
        CounterConsume::None => true,
        CounterConsume::Fixed(amount) => {
            amount > 0 && require.saturating_sub(amount) >= definition.min
        }
        CounterConsume::All => definition.min <= 0 && definition.max >= 0,
    };
    if !valid {
        return Err(mlua::Error::runtime(format!(
            "counter {name:?} has an invalid consumption cost"
        )));
    }
    Ok(())
}

fn parse_counter_consume(value: Value, name: &str) -> mlua::Result<CounterConsume> {
    match value {
        Value::Nil => Ok(CounterConsume::None),
        Value::Integer(value) => i32::try_from(value)
            .map(CounterConsume::Fixed)
            .map_err(|_| mlua::Error::runtime(format!("counter {name:?} consume overflows i32"))),
        Value::String(value) if value.to_str()?.as_ref() == "all" => Ok(CounterConsume::All),
        _ => Err(mlua::Error::runtime(format!(
            "counter {name:?} has invalid consume value"
        ))),
    }
}

fn required_string(table: &Table, field: &str) -> mlua::Result<String> {
    let value: String = table.get(field)?;
    if value.is_empty() {
        return Err(mlua::Error::runtime(format!(
            "field {field:?} must not be empty"
        )));
    }
    Ok(value)
}

fn lua_error(error: impl ToString) -> mlua::Error {
    mlua::Error::runtime(error.to_string())
}

fn seal_handlers(lua: &Lua, handlers: &HashMap<HandlerId, RegistryKey>) -> mlua::Result<()> {
    let environment = sealed_environment(lua)?;
    for key in handlers.values() {
        seal_handler(lua, key, &environment)?;
    }
    Ok(())
}

fn sealed_environment(lua: &Lua) -> mlua::Result<Table> {
    let environment = lua.create_table()?;
    let metatable = lua.create_table()?;
    metatable.set("__index", lua.globals())?;
    metatable.set(
        "__newindex",
        lua.create_function(|_, (_table, key, _value): (Table, Value, Value)| {
            Err::<(), _>(mlua::Error::runtime(format!(
                "rule attempted to write global {key:?}"
            )))
        })?,
    )?;
    metatable.set("__metatable", false)?;
    environment.set_metatable(Some(metatable))?;
    Ok(environment)
}

fn seal_handler(lua: &Lua, key: &RegistryKey, environment: &Table) -> mlua::Result<()> {
    let function: Function = lua.registry_value(key)?;
    if function.info().num_upvalues == 0 {
        return Ok(());
    }
    if !function.set_environment(environment.clone())? {
        return Err(mlua::Error::runtime(
            "rule handler has no replaceable environment",
        ));
    }
    Ok(())
}

fn context_table(lua: &Lua, context: &RuleContext) -> mlua::Result<Table> {
    let table = lua.create_table()?;
    set_context_entities(lua, &table, context)?;
    set_context_action(&table, context)?;
    set_context_event(lua, &table, context)?;
    Ok(table)
}

fn set_context_entities(lua: &Lua, table: &Table, context: &RuleContext) -> mlua::Result<()> {
    if let Some(actor) = context.actor {
        table.set("actor", entity_table(lua, actor)?)?;
    }
    set_context_source(lua, table, context.source)?;
    if let Some(target) = context.target {
        table.set("target", entity_table(lua, target)?)?;
    }
    Ok(())
}

fn set_context_source(lua: &Lua, table: &Table, source: Option<EntityRef>) -> mlua::Result<()> {
    if let Some(source) = source {
        table.set("source", entity_table(lua, source)?)?;
        table.set("owner", source.player())?;
    }
    Ok(())
}

fn set_context_action(table: &Table, context: &RuleContext) -> mlua::Result<()> {
    table.set("action", context.action_id.as_deref())?;
    table.set(
        "action_kind",
        context.action_kind.map(|kind| kind.to_string()),
    )?;
    table.set("skill", context.skill.map(|skill| skill.to_string()))?;
    table.set("option", context.option.as_deref())?;
    table.set("charged", context.traits.charged)?;
    table.set("plunging", context.traits.plunging)?;
    Ok(())
}

fn set_context_event(lua: &Lua, table: &Table, context: &RuleContext) -> mlua::Result<()> {
    if let Some(event) = &context.event {
        table.set("event", event_table(lua, event)?)?;
    }
    Ok(())
}

fn event_table(lua: &Lua, event: &crate::Event) -> mlua::Result<Table> {
    let table = lua.create_table()?;
    table.set("player", event.player)?;
    table.set("amount", event.amount)?;
    table.set("charged", event.traits.charged)?;
    table.set("plunging", event.traits.plunging)?;
    set_event_action(&table, event)?;
    set_event_damage(&table, event)?;
    Ok(table)
}

fn set_event_action(table: &Table, event: &crate::Event) -> mlua::Result<()> {
    table.set("action", event.action_id.as_deref())?;
    table.set(
        "action_kind",
        event.action_kind.map(|kind| kind.to_string()),
    )?;
    table.set("skill", event.skill.map(|skill| skill.to_string()))
}

fn set_event_damage(table: &Table, event: &crate::Event) -> mlua::Result<()> {
    table.set("element", event.element.map(|element| element.to_string()))?;
    table.set(
        "reaction",
        event.reaction.map(|reaction| reaction.to_string()),
    )
}

fn entity_table(lua: &Lua, entity: EntityRef) -> mlua::Result<Table> {
    let table = lua.create_table()?;
    match entity {
        EntityRef::Character { player, slot } => {
            table.set("kind", "character")?;
            table.set("player", player)?;
            table.set("slot", slot)?;
        }
        EntityRef::Modifier { player, instance } => {
            table.set("kind", "modifier")?;
            table.set("player", player)?;
            table.set("instance", instance)?;
        }
    }
    Ok(table)
}

fn parse_effects(lua: &Lua, value: Value) -> mlua::Result<Vec<Effect>> {
    if value == Value::Nil {
        return Ok(Vec::new());
    }
    lua.from_value(value)
}

pub(crate) fn resolve_target(
    state: &GameState,
    context: &RuleContext,
    target: TargetRef,
) -> Result<EntityRef> {
    match target {
        TargetRef::Actor => context
            .actor
            .ok_or_else(|| EngineError::Rule("context has no actor".to_owned())),
        TargetRef::Source => context
            .source
            .ok_or_else(|| EngineError::Rule("context has no source".to_owned())),
        TargetRef::EventTarget => context
            .target
            .ok_or_else(|| EngineError::Rule("context has no target".to_owned())),
        TargetRef::OwnActive => context
            .source
            .map(|source| state.active_character(source.player()))
            .ok_or_else(|| EngineError::Rule("context has no source".to_owned())),
        TargetRef::EnemyActive => context
            .source
            .map(|source| state.active_character(1 - source.player()))
            .ok_or_else(|| EngineError::Rule("context has no source".to_owned())),
    }
}
