modifier {
    id = "mualani.shark_missile",
    name = "鲨鲨飞弹",
    zone = "summon",
    merge = "add",
    counters = { uses = { initial = 2, min = 0, max = 99 } },
    remove_at_zero = "uses",
    handlers = {
        round_end = function(ctx)
            return {
                damage("enemy_active", "hydro", 2),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

character {
    id = "mualani",
    name = "玛拉妮",
    element = "hydro",
    tags = { "catalyst", "natlan" },
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        energy = { initial = 0, min = 0, max = 2 },
        nightsoul = { initial = 0, min = 0, max = 2 },
        bite_stacks = { initial = 0, min = 0, max = 99 },
    },
    actions = {
        {
            id = "cooling_treatment",
            name = "降温处理",
            kind = "normal_attack",
            cost = { dice = { hydro = 1, any = 2 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "hydro", 1),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "surfshark_wavebreaker",
            name = "踏鲨破浪",
            kind = "elemental_skill",
            cost = { dice = { hydro = 2 } },
            resolve = function(ctx)
                return { add_counter("actor", "nightsoul", 2) }
            end,
        },
        {
            id = "sharky_surfboard",
            name = "鲨鲨冲浪板",
            kind = "special",
            cost = {
                counters = { { name = "nightsoul", require = 1, consume = 1 } },
            },
            resolve = function(ctx)
                return { add_counter("actor", "bite_stacks", 1) }
            end,
        },
        {
            id = "boomsharka_laka",
            name = "爆瀑飞弹",
            kind = "elemental_burst",
            cost = {
                dice = { hydro = 3 },
                counters = { { name = "energy", require = 2, consume = 2 } },
            },
            resolve = function(ctx)
                return {
                    piercing("enemy", 1),
                    damage("enemy_active", "hydro", 2),
                    add_modifier("actor", "mualani.shark_missile"),
                }
            end,
        },
    },
}
