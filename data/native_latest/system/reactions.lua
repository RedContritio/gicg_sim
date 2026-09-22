modifier {
    id = "system.frozen",
    name = "冻结",
    zone = "character",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    remove_at_zero = "uses",
    handlers = {
        round_end = function(ctx)
            return { add_counter("source", "uses", -1) }
        end,
    },
}

modifier {
    id = "system.crystallize_shield",
    name = "结晶护盾",
    zone = "combat",
    merge = "add",
    counters = { points = { initial = 1, min = 0, max = 2 } },
    remove_at_zero = "points",
    handlers = {},
}

modifier {
    id = "system.burning_flame",
    name = "燃烧烈焰",
    zone = "summon",
    merge = "add",
    counters = { uses = { initial = 1, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {
        round_end = function(ctx)
            return {
                damage("enemy_active", "pyro", 1),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

modifier {
    id = "system.dendro_core",
    name = "草原核",
    zone = "combat",
    merge = "add",
    counters = { uses = { initial = 1, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {},
}

modifier {
    id = "system.catalyzing_field",
    name = "激化领域",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 2, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {},
}
