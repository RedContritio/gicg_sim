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
    ActionDefinition, ActionTags, ActionTempo, ChoiceOption, Cost, CounterConsume, CounterCost,
    CounterDefinition, CounterSchema, Effect, Element, EngineError, EntityRef, EventKind,
    GameState, HandlerDefinition, HandlerId, MergePolicy, ModifierDefinition, RemovalReason,
    Result, RuleContext, Ruleset, TargetRef, Zone,
};

struct LoadState {
    characters: Vec<crate::CharacterDefinition>,
    modifiers: Vec<ModifierDefinition>,
    handlers: HashMap<HandlerId, RegistryKey>,
    next_handler: HandlerId,
}

impl LoadState {
    fn new() -> Self {
        Self {
            characters: Vec::new(),
            modifiers: Vec::new(),
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
        if info.num_upvalues != 1 || function.environment().is_none() {
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
        if files.is_empty() {
            return Err(EngineError::InvalidRuleset(format!(
                "{} contains no Lua files",
                root.display()
            )));
        }
        let lua = Lua::new_with(
            StdLib::TABLE | StdLib::STRING | StdLib::MATH | StdLib::UTF8,
            LuaOptions::default(),
        )?;
        install_effect_constructors(&lua)?;
        let state = Rc::new(RefCell::new(LoadState::new()));
        install_definition_functions(&lua, Rc::clone(&state))?;

        let mut digest = Sha256::new();
        for path in files {
            let relative = path.strip_prefix(&root).map_err(|error| {
                EngineError::InvalidRuleset(format!("resolve ruleset path: {error}"))
            })?;
            let source = fs::read(&path)?;
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
                })?;
        }

        lua.globals().set("character", Value::Nil)?;
        lua.globals().set("modifier", Value::Nil)?;
        for name in ["_G", "load", "dofile", "loadfile", "collectgarbage"] {
            lua.globals().set(name, Value::Nil)?;
        }
        lua.gc_collect()?;
        let state = Rc::try_unwrap(state)
            .map_err(|_| EngineError::InvalidRuleset("ruleset loader leaked state".to_owned()))?
            .into_inner();
        seal_handlers(&lua, &state.handlers)?;
        let hash = digest
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        let rules = Ruleset::new(hash, state.characters, state.modifiers)?;
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
                    let target = TargetRef::parse(&target)
                        .ok_or_else(|| mlua::Error::runtime("unknown counter target"))?;
                    let entity = resolve_target(state, context, target)
                        .map_err(|error| mlua::Error::runtime(error.to_string()))?;
                    state
                        .counter(&self.rules, entity, &name)
                        .map_err(|error| mlua::Error::runtime(error.to_string()))
                })?;
                table.set("counter", counter)?;
                let value: Value = function.call(table)?;
                parse_effects(value, &self.rules, context)
                    .map_err(|error| mlua::Error::runtime(error.to_string()))
            })
            .map_err(EngineError::from)
    }
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
    lua.globals().set(
        "modifier",
        lua.create_function(move |lua, table: Table| {
            let definition = parse_modifier(lua, &mut state.borrow_mut(), table)?;
            state.borrow_mut().modifiers.push(definition);
            Ok(())
        })?,
    )?;
    Ok(())
}

fn parse_character(
    lua: &Lua,
    state: &mut LoadState,
    table: Table,
) -> mlua::Result<crate::CharacterDefinition> {
    let id = required_string(&table, "id")?;
    let name = required_string(&table, "name")?;
    let element = Element::parse(&required_string(&table, "element")?)
        .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    let counters = parse_counters(table.get("counters")?)?;
    if counters.field("hp").is_none() {
        return Err(mlua::Error::runtime(format!(
            "character {id:?} has no hp counter"
        )));
    }
    let action_tables: Table = table.get("actions")?;
    let mut actions = Vec::new();
    for action in action_tables.sequence_values::<Table>() {
        actions.push(parse_action(lua, state, &id, action?, &counters)?);
    }
    if actions.is_empty() {
        return Err(mlua::Error::runtime(format!(
            "character {id:?} has no actions"
        )));
    }
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
    let tempo = ActionTempo::parse(
        table
            .get::<Option<String>>("tempo")?
            .as_deref()
            .unwrap_or("combat"),
    )
    .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    let mut tags = ActionTags::default();
    for tag in table.get::<Table>("tags")?.sequence_values::<String>() {
        tags.insert_name(&tag?)
            .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    }
    if tags.0 == 0 {
        return Err(mlua::Error::runtime(format!(
            "action {character_id}.{id} has no tags"
        )));
    }
    let cost = match table.get::<Option<Table>>("cost")? {
        Some(value) => parse_cost(value, counters)?,
        None => Cost::default(),
    };
    let resolve = state.add_handler(
        lua,
        table.get("resolve")?,
        &format!("action {character_id}.{id} resolve"),
    )?;
    let mut continuations = HashMap::new();
    if let Some(entries) = table.get::<Option<Table>>("continue")? {
        for entry in entries.pairs::<String, Function>() {
            let (name, function) = entry?;
            let handler = state.add_handler(
                lua,
                function,
                &format!("action {character_id}.{id} continuation {name}"),
            )?;
            continuations.insert(name, handler);
        }
    }
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
    let zone = Zone::parse(
        table
            .get::<Option<String>>("zone")?
            .as_deref()
            .unwrap_or("character"),
    )
    .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    let merge = MergePolicy::parse(
        table
            .get::<Option<String>>("merge")?
            .as_deref()
            .unwrap_or("replace"),
    )
    .map_err(|error| mlua::Error::runtime(error.to_string()))?;
    let counters = parse_counters(table.get("counters")?)?;
    let remove_at_zero = table
        .get::<Option<String>>("remove_at_zero")?
        .map(|name| {
            counters.field(&name).ok_or_else(|| {
                mlua::Error::runtime(format!(
                    "modifier {id:?} remove_at_zero counter {name:?} does not exist"
                ))
            })
        })
        .transpose()?;
    let mut handlers: HashMap<EventKind, Vec<HandlerDefinition>> = HashMap::new();
    if let Some(entries) = table.get::<Option<Table>>("handlers")? {
        for entry in entries.pairs::<String, Function>() {
            let (event_name, function) = entry?;
            let event = EventKind::parse(&event_name)
                .map_err(|error| mlua::Error::runtime(error.to_string()))?;
            let handler = state.add_handler(
                lua,
                function,
                &format!("modifier {id} handler {event_name}"),
            )?;
            handlers.entry(event).or_default().push(HandlerDefinition {
                event,
                priority: 0,
                handler,
            });
        }
    }
    let mut abilities = HashMap::new();
    if let Some(entries) = table.get::<Option<Table>>("abilities")? {
        for entry in entries.pairs::<String, Function>() {
            let (ability, function) = entry?;
            let handler =
                state.add_handler(lua, function, &format!("modifier {id} ability {ability}"))?;
            abilities.insert(ability, handler);
        }
    }
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
    if let Some(dice) = table.get::<Option<Table>>("dice")? {
        for entry in dice.pairs::<String, u8>() {
            let (name, count) = entry?;
            if name == "any" {
                cost.any = count;
            } else {
                let die = crate::Die::parse(&name)
                    .map_err(|error| mlua::Error::runtime(error.to_string()))?;
                if die == crate::Die::Omni {
                    return Err(mlua::Error::runtime("omni cannot be a specific dice cost"));
                }
                cost.dice.set(die, count);
            }
        }
    }
    if let Some(entries) = table.get::<Option<Table>>("counters")? {
        for entry in entries.sequence_values::<Table>() {
            let entry = entry?;
            let name = required_string(&entry, "name")?;
            let field = counters.field(&name).ok_or_else(|| {
                mlua::Error::runtime(format!("counter cost refers to unknown counter {name:?}"))
            })?;
            let consume = match entry.get::<Value>("consume")? {
                Value::Nil => CounterConsume::None,
                Value::Integer(value) => {
                    CounterConsume::Fixed(i32::try_from(value).map_err(|_| {
                        mlua::Error::runtime(format!("counter {name:?} consume overflows i32"))
                    })?)
                }
                Value::String(value) if value.to_str()?.as_ref() == "all" => CounterConsume::All,
                _ => {
                    return Err(mlua::Error::runtime(format!(
                        "counter {name:?} has invalid consume value"
                    )));
                }
            };
            cost.counters.push(CounterCost {
                field,
                require: entry.get("require")?,
                consume,
            });
        }
    }
    Ok(cost)
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
    for key in handlers.values() {
        let function: Function = lua.registry_value(key)?;
        if !function.set_environment(environment.clone())? {
            return Err(mlua::Error::runtime(
                "rule handler has no replaceable environment",
            ));
        }
    }
    Ok(())
}

fn context_table(lua: &Lua, context: &RuleContext) -> mlua::Result<Table> {
    let table = lua.create_table()?;
    if let Some(actor) = context.actor {
        table.set("actor", entity_table(lua, actor)?)?;
    }
    if let Some(source) = context.source {
        table.set("source", entity_table(lua, source)?)?;
        table.set("owner", source.player())?;
    }
    if let Some(target) = context.target {
        table.set("target", entity_table(lua, target)?)?;
    }
    if let Some(action_id) = &context.action_id {
        table.set("action", action_id.as_str())?;
    }
    if let Some(option) = &context.option {
        table.set("option", option.as_str())?;
    }
    if let Some(event) = &context.event {
        let event_table = lua.create_table()?;
        event_table.set("player", event.player)?;
        event_table.set("action", event.action_id.as_deref())?;
        event_table.set("amount", event.amount)?;
        event_table.set("element", event.element.map(|element| element.to_string()))?;
        table.set("event", event_table)?;
    }
    Ok(table)
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
        "set_counter" => Ok(Effect::SetCounter {
            target: effect_target(&table)?,
            name: table.get("name")?,
            value: table.get("value")?,
        }),
        "add_counter" => Ok(Effect::AddCounter {
            target: effect_target(&table)?,
            name: table.get("name")?,
            delta: table.get("delta")?,
        }),
        "damage" => {
            let amount: i32 = table.get("amount")?;
            if amount < 0 {
                return Err(EngineError::Rule(format!(
                    "damage amount {amount} is negative"
                )));
            }
            Ok(Effect::Damage {
                target: effect_target(&table)?,
                element: Element::parse(&table.get::<String>("element")?)?,
                amount,
            })
        }
        "add_modifier" => {
            let id: String = table.get("definition")?;
            let definition = rules
                .modifier(&id)
                .ok_or_else(|| EngineError::Rule(format!("modifier {id:?} is not defined")))?;
            Ok(Effect::AddModifier {
                target: effect_target(&table)?,
                definition: definition.definition,
            })
        }
        "remove_modifier" => Ok(Effect::RemoveModifier {
            target: effect_target(&table)?,
            reason: parse_removal_reason(&table.get::<String>("reason")?)?,
        }),
        "choice" => {
            let actor = context.actor.ok_or_else(|| {
                EngineError::Rule("choice requires an acting character".to_owned())
            })?;
            let mut options = Vec::new();
            for value in table.get::<Table>("options")?.sequence_values::<Value>() {
                match value? {
                    Value::String(value) => {
                        let id = value.to_str()?.to_owned();
                        options.push(ChoiceOption {
                            label: id.clone(),
                            id,
                        });
                    }
                    Value::Table(value) => {
                        let id: String = value.get("id")?;
                        let label = value
                            .get::<Option<String>>("label")?
                            .unwrap_or_else(|| id.clone());
                        options.push(ChoiceOption { id, label });
                    }
                    _ => {
                        return Err(EngineError::Rule(
                            "choice option must be a string or table".to_owned(),
                        ));
                    }
                }
            }
            if options.is_empty() {
                return Err(EngineError::Rule("choice has no options".to_owned()));
            }
            Ok(Effect::Choice {
                player: actor.player(),
                options,
                continuation: table.get("continuation")?,
            })
        }
        "activate" => Ok(Effect::ActivateAbility {
            target: effect_target(&table)?,
            ability: table.get("ability")?,
        }),
        _ => Err(EngineError::Rule(format!("unknown effect kind {kind:?}"))),
    }
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
