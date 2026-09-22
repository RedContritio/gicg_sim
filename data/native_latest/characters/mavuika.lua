modifier {
    id = "mavuika.fighting_spirit",
    name = "战意汇聚",
    zone = "character",
    merge = "replace",
    counters = {},
    handlers = {
        action_resolved = function(ctx)
            if ctx.event.player ~= ctx.owner
                or ctx.actor_definition ~= "mavuika"
                or ctx.event.skill ~= "normal_attack" then
                return nil
            end
            return { add_character_counter("mavuika", "fighting_spirit", 1) }
        end,
    },
}

modifier {
    id = "mavuika.ring_of_searing_radiance",
    name = "诸火武装·焚曜之环",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 2, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {
        action_resolved = function(ctx)
            if ctx.event.player ~= ctx.owner or ctx.actor_definition == "mavuika" then
                return nil
            end
            return {
                damage("enemy_active", "pyro", 1),
                add_counter("source", "uses", -1),
                add_character_counter("mavuika", "fighting_spirit", 1),
            }
        end,
    },
}

modifier {
    id = "mavuika.crucible_of_death_and_life",
    name = "死生之炉",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 2, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {},
}

character {
    id = "mavuika",
    name = "玛薇卡",
    element = "pyro",
    passives = { "mavuika.fighting_spirit" },
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        fighting_spirit = { initial = 0, min = 0, max = 6 },
        nightsoul = { initial = 0, min = 0, max = 2 },
    },
    actions = {
        {
            id = "flames_weave_life",
            name = "以火织命",
            kind = "normal_attack",
            cost = { dice = { pyro = 1, any = 2 } },
            resolve = function(ctx)
                return { damage("enemy_active", "physical", 2) }
            end,
        },
        {
            id = "the_named_moment",
            name = "称名之刻",
            kind = "elemental_skill",
            cost = { dice = { pyro = 3 } },
            resolve = function(ctx)
                return {
                    add_counter("actor", "nightsoul", 2),
                    add_modifier("actor", "mavuika.ring_of_searing_radiance"),
                    choose("motorcycle", {
                        { id = "leap", label = "驰轮车·跃升" },
                        { id = "traverse", label = "驰轮车·涉渡" },
                        { id = "sprint", label = "驰轮车·疾驰" },
                    }),
                }
            end,
            continue = {
                motorcycle = function(ctx)
                    return { add_card("mavuika.motorcycle_" .. ctx.option) }
                end,
            },
        },
        {
            id = "hour_of_burning_skies",
            name = "燔天之时",
            kind = "elemental_burst",
            cost = {
                dice = { pyro = 4 },
                counters = { { name = "fighting_spirit", require = 3 } },
            },
            resolve = function(ctx)
                local spirit = ctx.counter("actor", "fighting_spirit")
                local effects = {
                    damage("enemy_active", "pyro", spirit),
                    add_counter("actor", "fighting_spirit", -spirit),
                    add_counter("actor", "nightsoul", 1),
                }
                if spirit == 6 then
                    effects[#effects + 1] = add_modifier(
                        "actor", "mavuika.crucible_of_death_and_life"
                    )
                end
                return effects
            end,
        },
    },
}
