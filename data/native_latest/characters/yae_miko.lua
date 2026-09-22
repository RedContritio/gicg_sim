modifier {
    id = "yae_miko.sesshou_sakura",
    name = "杀生樱",
    zone = "summon",
    merge = "add",
    counters = {
        uses = { initial = 3, min = 0, max = 6 },
        power = { initial = 0, min = 0, max = 1 },
    },
    remove_at_zero = "uses",
    handlers = {
        player_end_declared = function(ctx)
            local uses = ctx.counter("source", "uses")
            if ctx.event.player ~= ctx.owner or uses < 4 then
                return nil
            end
            return {
                damage("enemy_active", "electro", 1),
                add_counter("source", "uses", -1),
            }
        end,
        round_end = function(ctx)
            local power = ctx.counter("source", "power")
            return {
                damage("enemy_active", "electro", 1 + power),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

modifier {
    id = "yae_miko.tenko_thunderbolts",
    name = "天狐霆雷",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    remove_at_zero = "uses",
    handlers = {
        action_resolved = function(ctx)
            if ctx.event.player ~= ctx.owner or ctx.event.action == "great_secret_art" then
                return nil
            end
            return {
                damage("enemy_active", "electro", 3),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

character {
    id = "yae_miko",
    name = "八重神子",
    element = "electro",
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        energy = { initial = 0, min = 0, max = 2 },
    },
    actions = {
        {
            id = "spiritfox_sin_eater",
            name = "狐灵食罪式",
            kind = "normal_attack",
            cost = { dice = { electro = 1, any = 2 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "electro", 1),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "yakan_evocation_sesshou_sakura",
            name = "野干役咒·杀生樱",
            kind = "elemental_skill",
            cost = { dice = { electro = 3 } },
            resolve = function(ctx)
                local existing = ctx.modifier_counter("yae_miko.sesshou_sakura", "uses")
                if existing == 0 then
                    return { add_modifier("actor", "yae_miko.sesshou_sakura") }
                end
                return {
                    add_modifier("actor", "yae_miko.sesshou_sakura"),
                    add_modifier_counter("yae_miko.sesshou_sakura", "power", 1),
                }
            end,
        },
        {
            id = "great_secret_art",
            name = "大密法·天狐显真",
            kind = "elemental_burst",
            cost = {
                dice = { electro = 3 },
                counters = { { name = "energy", require = 2, consume = 2 } },
            },
            resolve = function(ctx)
                local uses = ctx.modifier_counter("yae_miko.sesshou_sakura", "uses")
                local effects = { damage("enemy_active", "electro", 4) }
                if uses > 0 then
                    effects[#effects + 1] = add_modifier_counter(
                        "yae_miko.sesshou_sakura", "uses", -uses
                    )
                    effects[#effects + 1] = add_modifier("actor", "yae_miko.tenko_thunderbolts")
                end
                return effects
            end,
        },
    },
}
