modifier {
    id = "card.travelers_handy_sword",
    name = "旅行剑",
    zone = "character",
    slot = "weapon",
    merge = "replace",
    counters = {},
    damage = {
        direction = "outgoing",
        elements = { "physical" },
        delta = 1,
    },
    handlers = {},
}

modifier {
    id = "card.knights_of_favonius_library",
    name = "骑士团图书馆",
    zone = "support",
    merge = "replace",
    counters = {},
    roll = { rerolls = 1 },
    handlers = {},
}

modifier {
    id = "card.paimon",
    name = "派蒙",
    zone = "support",
    merge = "replace",
    counters = { uses = { initial = 2, min = 0, max = 2 } },
    remove_at_zero = "uses",
    handlers = {
        round_start = function(ctx)
            return {
                add_dice("omni", 2),
                add_counter("source", "uses", -1),
            }
        end,
    },
}

card {
    id = "travelers_handy_sword",
    name = "旅行剑",
    description = "所附属角色造成的物理伤害+1。",
    kind = "equipment",
    tempo = "fast",
    cost = { dice = { any = 2 } },
    target = { side = "own", state = "alive" },
    resolve = function(ctx)
        return { add_modifier("target", "card.travelers_handy_sword") }
    end,
}

card {
    id = "knights_of_favonius_library",
    name = "骑士团图书馆",
    description = "每个投掷阶段额外获得1次重掷机会。",
    kind = "support",
    tempo = "fast",
    cost = { dice = { same = 1 } },
    resolve = function(ctx)
        return { add_modifier("own_active", "card.knights_of_favonius_library") }
    end,
}

card {
    id = "paimon",
    name = "派蒙",
    description = "回合开始时生成2个万能元素骰，可用2次。",
    kind = "support",
    tempo = "fast",
    cost = { dice = { same = 3 } },
    resolve = function(ctx)
        return { add_modifier("own_active", "card.paimon") }
    end,
}
