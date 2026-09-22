use std::{
    cell::RefCell,
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
};

use mlua::{Function, Lua, LuaOptions, RegistryKey, StdLib, Table, Value};
use sha2::{Digest, Sha256};

use crate::{
    ActionDefinition, ActionTags, ActionTempo, CardDefinition, ChoiceOption, Cost, CounterConsume,
    CounterCost, CounterDefinition, CounterSchema, Effect, Element, EngineError, EntityRef,
    EventKind, GameState, HandlerDefinition, HandlerId, MergePolicy, ModifierDefinition,
    RemovalReason, Result, RuleContext, Ruleset, TargetRef, Zone,
};

struct LoadState {
    characters: Vec<crate::CharacterDefinition>,
    modifiers: Vec<ModifierDefinition>,
    cards: Vec<CardDefinition>,
    handlers: HashMap<HandlerId, RegistryKey>,
    next_handler: HandlerId,
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
        let state = Rc::new(RefCell::new(LoadState::new()));
        install_definition_functions(&lua, Rc::clone(&state))?;
        let hash = execute_files(&lua, root, files)?;
        lock_runtime(&lua)?;
        let state = take_load_state(state)?;
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
                let counter = scope.create_function(|_, (target, name): (String, String)| {
                    read_counter(state, &self.rules, context, &target, &name)
                })?;
                table.set("counter", counter)?;
                let value: Value = function.call(table)?;
                parse_effects(value, &self.rules, context)
                    .map_err(|error| mlua::Error::runtime(error.to_string()))
            })
            .map_err(EngineError::from)
    }
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

fn take_load_state(state: Rc<RefCell<LoadState>>) -> Result<LoadState> {
    Ok(Rc::try_unwrap(state)
        .map_err(|_| EngineError::InvalidRuleset("ruleset loader leaked state".to_owned()))?
        .into_inner())
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
    let entity = resolve_target(state, context, target)
        .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    state
        .counter(rules, entity, name)
        .map_err(|error| mlua::Error::runtime(error.to_string()))
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
        function set_counter(target, name, value)
            return { kind = "set_counter", target = target, name = name, value = value }
        end
        function add_counter(target, name, delta)
            return { kind = "add_counter", target = target, name = name, delta = delta }
        end
        function damage(target, element, amount)
            return { kind = "damage", target = target, element = element, amount = amount }
        end
        function add_modifier(target, definition)
            return { kind = "add_modifier", target = target, definition = definition }
        end
        function remove_modifier(target, reason)
            return { kind = "remove_modifier", target = target, reason = reason }
        end
        function choose(continuation, options)
            return { kind = "choice", continuation = continuation, options = options }
        end
        function activate(target, ability)
            return { kind = "activate", target = target, ability = ability }
        end
        "#,
    )
    .exec()
}

fn install_definition_functions(lua: &Lua, state: Rc<RefCell<LoadState>>) -> mlua::Result<()> {
    let character_state = Rc::clone(&state);
    lua.globals().set(
        "character",
        lua.create_function(move |lua, table: Table| {
            let definition = parse_character(lua, &mut character_state.borrow_mut(), table)?;
            character_state.borrow_mut().characters.push(definition);
            Ok(())
        })?,
    )?;
    let modifier_state = Rc::clone(&state);
    lua.globals().set(
        "modifier",
        lua.create_function(move |lua, table: Table| {
            let definition = parse_modifier(lua, &mut modifier_state.borrow_mut(), table)?;
            modifier_state.borrow_mut().modifiers.push(definition);
            Ok(())
        })?,
    )?;
    lua.globals().set(
        "card",
        lua.create_function(move |lua, table: Table| {
            let definition = parse_card(lua, &mut state.borrow_mut(), table)?;
            state.borrow_mut().cards.push(definition);
            Ok(())
        })?,
    )?;
    Ok(())
}

fn parse_card(lua: &Lua, state: &mut LoadState, table: Table) -> mlua::Result<CardDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let description = required_string(&table, "description")?;
    let tempo = parse_tempo(&table, "fast")?;
    let cost = parse_optional_cost(&table, &CounterSchema::default())?;
    let resolve = add_table_handler(lua, state, &table, "resolve", &format!("card {id} resolve"))?;
    Ok(CardDefinition {
        definition: 0,
        id: id.clone(),
        name: name.clone(),
        description,
        action: ActionDefinition {
            id,
            name,
            tags: ActionTags(ActionTags::CARD),
            tempo,
            cost,
            resolve,
            continuations: HashMap::new(),
        },
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
    crate::CharacterDefinition::new(id, name, element, counters, actions)
        .map_err(|error| mlua::Error::runtime(error.to_string()))
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
    let tempo = parse_tempo(&table, "combat")?;
    let tags = parse_action_tags(&table, character_id, &id)?;
    let cost = parse_optional_cost(&table, counters)?;
    let label = format!("action {character_id}.{id} resolve");
    let resolve = add_table_handler(lua, state, &table, "resolve", &label)?;
    let continuations = parse_continuations(lua, state, &table, character_id, &id)?;
    Ok(ActionDefinition {
        id,
        name,
        tags,
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
    let merge = parse_merge(&table)?;
    let counters = parse_counters(table.get("counters")?)?;
    let remove_at_zero = parse_remove_at_zero(&table, &id, &counters)?;
    let handlers = parse_handlers(lua, state, &table, &id)?;
    let abilities = parse_abilities(lua, state, &table, &id)?;
    Ok(ModifierDefinition {
        definition: 0,
        id,
        name,
        zone,
        counters,
        merge,
        remove_at_zero,
        handlers,
        abilities,
    })
}

fn parse_tempo(table: &Table, default: &str) -> mlua::Result<ActionTempo> {
    let value = table.get::<Option<String>>("tempo")?;
    ActionTempo::parse(value.as_deref().unwrap_or(default))
        .map_err(|error| mlua::Error::runtime(error.to_string()))
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
    Element::parse(&required_string(table, "element")?)
        .map_err(|error| mlua::Error::runtime(error.to_string()))
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

fn parse_action_tags(
    table: &Table,
    character_id: &str,
    action_id: &str,
) -> mlua::Result<ActionTags> {
    let mut tags = ActionTags::default();
    for tag in table.get::<Table>("tags")?.sequence_values::<String>() {
        tags.insert_name(&tag?)
            .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    }
    if tags.0 == 0 {
        return Err(mlua::Error::runtime(format!(
            "action {character_id}.{action_id} has no tags"
        )));
    }
    Ok(tags)
}

fn parse_continuations(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    character_id: &str,
    action_id: &str,
) -> mlua::Result<HashMap<String, HandlerId>> {
    let mut continuations = HashMap::new();
    let Some(entries) = table.get::<Option<Table>>("continue")? else {
        return Ok(continuations);
    };
    for entry in entries.pairs::<String, Function>() {
        let (name, function) = entry?;
        let label = format!("action {character_id}.{action_id} continuation {name}");
        continuations.insert(name, state.add_handler(lua, function, &label)?);
    }
    Ok(continuations)
}

fn parse_zone(table: &Table) -> mlua::Result<Zone> {
    let value = table.get::<Option<String>>("zone")?;
    Zone::parse(value.as_deref().unwrap_or("character"))
        .map_err(|error| mlua::Error::runtime(error.to_string()))
}

fn parse_merge(table: &Table) -> mlua::Result<MergePolicy> {
    let value = table.get::<Option<String>>("merge")?;
    MergePolicy::parse(value.as_deref().unwrap_or("replace"))
        .map_err(|error| mlua::Error::runtime(error.to_string()))
}

fn parse_remove_at_zero(
    table: &Table,
    modifier_id: &str,
    counters: &CounterSchema,
) -> mlua::Result<Option<u16>> {
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
) -> mlua::Result<HashMap<EventKind, Vec<HandlerDefinition>>> {
    let mut handlers: HashMap<EventKind, Vec<HandlerDefinition>> = HashMap::new();
    let Some(entries) = table.get::<Option<Table>>("handlers")? else {
        return Ok(handlers);
    };
    for entry in entries.pairs::<String, Function>() {
        let (event_name, function) = entry?;
        let event = EventKind::parse(&event_name)
            .map_err(|error| mlua::Error::runtime(error.to_string()))?;
        let label = format!("modifier {modifier_id} handler {event_name}");
        let handler = state.add_handler(lua, function, &label)?;
        handlers.entry(event).or_default().push(HandlerDefinition {
            event,
            priority: 0,
            handler,
        });
    }
    Ok(handlers)
}

fn parse_abilities(
    lua: &Lua,
    state: &mut LoadState,
    table: &Table,
    modifier_id: &str,
) -> mlua::Result<HashMap<String, HandlerId>> {
    let mut abilities = HashMap::new();
    let Some(entries) = table.get::<Option<Table>>("abilities")? else {
        return Ok(abilities);
    };
    for entry in entries.pairs::<String, Function>() {
        let (ability, function) = entry?;
        let label = format!("modifier {modifier_id} ability {ability}");
        abilities.insert(ability, state.add_handler(lua, function, &label)?);
    }
    Ok(abilities)
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
    CounterSchema::new(counters).map_err(|error| mlua::Error::runtime(error.to_string()))
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
        if name == "any" {
            cost.any = count;
        } else {
            cost.dice.set(parse_specific_die(&name)?, count);
        }
    }
    Ok(())
}

fn parse_specific_die(name: &str) -> mlua::Result<crate::Die> {
    let die = crate::Die::parse(name).map_err(|error| mlua::Error::runtime(error.to_string()))?;
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
        cost.counters.push(parse_counter_cost(entry?, counters)?);
    }
    Ok(())
}

fn parse_counter_cost(entry: Table, counters: &CounterSchema) -> mlua::Result<CounterCost> {
    let name = required_string(&entry, "name")?;
    let field = counters.field(&name).ok_or_else(|| {
        mlua::Error::runtime(format!("counter cost refers to unknown counter {name:?}"))
    })?;
    Ok(CounterCost {
        field,
        require: entry.get("require")?,
        consume: parse_counter_consume(entry.get("consume")?, &name)?,
    })
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
    if let Some(action_id) = &context.action_id {
        table.set("action", action_id.as_str())?;
    }
    if let Some(option) = &context.option {
        table.set("option", option.as_str())?;
    }
    Ok(())
}

fn set_context_event(lua: &Lua, table: &Table, context: &RuleContext) -> mlua::Result<()> {
    if let Some(event) = &context.event {
        let event_table = lua.create_table()?;
        event_table.set("player", event.player)?;
        event_table.set("action", event.action_id.as_deref())?;
        event_table.set("amount", event.amount)?;
        event_table.set("element", event.element.map(|element| element.to_string()))?;
        table.set("event", event_table)?;
    }
    Ok(())
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

fn parse_effects(value: Value, rules: &Ruleset, context: &RuleContext) -> Result<Vec<Effect>> {
    if value == Value::Nil {
        return Ok(Vec::new());
    }
    let table = value
        .as_table()
        .ok_or_else(|| EngineError::Rule("handler must return an effect list or nil".to_owned()))?;
    let mut effects = Vec::new();
    for value in table.clone().sequence_values::<Table>() {
        let effect = value.map_err(EngineError::from)?;
        effects.push(parse_effect(effect, rules, context)?);
    }
    Ok(effects)
}

fn parse_effect(table: Table, rules: &Ruleset, context: &RuleContext) -> Result<Effect> {
    let kind: String = table.get("kind")?;
    match kind.as_str() {
        "set_counter" => parse_set_counter(&table),
        "add_counter" => parse_add_counter(&table),
        "damage" => parse_damage(&table),
        "add_modifier" => parse_add_modifier(&table, rules),
        "remove_modifier" => parse_remove_modifier(&table),
        "choice" => parse_choice(&table, context),
        "activate" => parse_activate(&table),
        _ => Err(EngineError::Rule(format!("unknown effect kind {kind:?}"))),
    }
}

fn parse_set_counter(table: &Table) -> Result<Effect> {
    Ok(Effect::SetCounter {
        target: effect_target(table)?,
        name: table.get("name")?,
        value: table.get("value")?,
    })
}

fn parse_add_counter(table: &Table) -> Result<Effect> {
    Ok(Effect::AddCounter {
        target: effect_target(table)?,
        name: table.get("name")?,
        delta: table.get("delta")?,
    })
}

fn parse_damage(table: &Table) -> Result<Effect> {
    let amount: i32 = table.get("amount")?;
    if amount < 0 {
        return Err(EngineError::Rule(format!(
            "damage amount {amount} is negative"
        )));
    }
    Ok(Effect::Damage {
        target: effect_target(table)?,
        element: Element::parse(&table.get::<String>("element")?)?,
        amount,
    })
}

fn parse_add_modifier(table: &Table, rules: &Ruleset) -> Result<Effect> {
    let id: String = table.get("definition")?;
    let definition = rules
        .modifier(&id)
        .ok_or_else(|| EngineError::Rule(format!("modifier {id:?} is not defined")))?;
    Ok(Effect::AddModifier {
        target: effect_target(table)?,
        definition: definition.definition,
    })
}

fn parse_remove_modifier(table: &Table) -> Result<Effect> {
    Ok(Effect::RemoveModifier {
        target: effect_target(table)?,
        reason: parse_removal_reason(&table.get::<String>("reason")?)?,
    })
}

fn parse_choice(table: &Table, context: &RuleContext) -> Result<Effect> {
    let actor = context
        .actor
        .ok_or_else(|| EngineError::Rule("choice requires an acting character".to_owned()))?;
    let options = parse_choice_options(table)?;
    Ok(Effect::Choice {
        player: actor.player(),
        options,
        continuation: table.get("continuation")?,
    })
}

fn parse_choice_options(table: &Table) -> Result<Vec<ChoiceOption>> {
    let mut options = Vec::new();
    for value in table.get::<Table>("options")?.sequence_values::<Value>() {
        options.push(parse_choice_option(value?)?);
    }
    if options.is_empty() {
        return Err(EngineError::Rule("choice has no options".to_owned()));
    }
    Ok(options)
}

fn parse_choice_option(value: Value) -> Result<ChoiceOption> {
    match value {
        Value::String(value) => {
            let id = value.to_str()?.to_owned();
            Ok(ChoiceOption {
                label: id.clone(),
                id,
            })
        }
        Value::Table(value) => {
            let id: String = value.get("id")?;
            let label = value
                .get::<Option<String>>("label")?
                .unwrap_or_else(|| id.clone());
            Ok(ChoiceOption { id, label })
        }
        _ => Err(EngineError::Rule(
            "choice option must be a string or table".to_owned(),
        )),
    }
}

fn parse_activate(table: &Table) -> Result<Effect> {
    Ok(Effect::ActivateAbility {
        target: effect_target(table)?,
        ability: table.get("ability")?,
    })
}

fn effect_target(table: &Table) -> Result<TargetRef> {
    let value: String = table.get("target")?;
    TargetRef::parse(&value)
        .ok_or_else(|| EngineError::Rule(format!("unknown effect target {value:?}")))
}

fn parse_removal_reason(value: &str) -> Result<RemovalReason> {
    match value {
        "consumed" => Ok(RemovalReason::Consumed),
        "exhausted" => Ok(RemovalReason::Exhausted),
        "expired" => Ok(RemovalReason::Expired),
        "discarded" => Ok(RemovalReason::Discarded),
        "replaced" => Ok(RemovalReason::Replaced),
        "death" => Ok(RemovalReason::Death),
        _ => Err(EngineError::Rule(format!(
            "unknown removal reason {value:?}"
        ))),
    }
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
