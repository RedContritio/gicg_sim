modifier {
    id = "kaeya.icicle",
    name = "寒冰之棱",
    zone = "combat",
    merge = "replace",
    counters = {
        uses = { initial = 3, min = 0, max = 3 },
    },
    remove_at_zero = "uses",
    handlers = {
        switch = function(ctx)
            if ctx.event.player ~= ctx.owner then
                return nil
            end
            return {
                damage("enemy_active", "cryo", 2),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

character {
    id = "kaeya",
    name = "凯亚",
    element = "cryo",
    tags = { "sword", "mondstadt" },
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        energy = { initial = 0, min = 0, max = 2 },
    },
    actions = {
        {
            id = "ceremonial_bladework",
            name = "仪典剑术",
            kind = "normal_attack",
            cost = { dice = { cryo = 1, any = 2 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "physical", 2),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "frostgnaw",
            name = "霜袭",
            kind = "elemental_skill",
            cost = { dice = { cryo = 3 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "cryo", 3),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "glacial_waltz",
            name = "凛冽轮舞",
            kind = "elemental_burst",
            cost = {
                dice = { cryo = 4 },
                counters = {
                    { name = "energy", require = 2, consume = 2 },
                },
            },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "cryo", 1),
                    add_modifier("own_active", "kaeya.icicle"),
                }
            end,
        },
    },
}
