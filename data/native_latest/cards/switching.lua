modifier {
    id = "card.leave_it_to_me",
    name = "交给我吧！",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    remove_at_zero = "uses",
    action = {
        kinds = { "switch" },
        tempo = "fast",
        counter = "uses",
    },
    handlers = {},
}

modifier {
    id = "card.changing_shifts",
    name = "换班时间",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    remove_at_zero = "uses",
    action = {
        kinds = { "switch" },
        reduce_dice = 1,
        counter = "uses",
    },
    handlers = {},
}

card {
    id = "leave_it_to_me",
    name = "交给我吧！",
    description = "下一次切换角色视为快速行动。",
    tempo = "fast",
    resolve = function(ctx)
        return { add_modifier("own_active", "card.leave_it_to_me") }
    end,
}

card {
    id = "changing_shifts",
    name = "换班时间",
    description = "下一次切换角色少花费1个元素骰。",
    tempo = "fast",
    resolve = function(ctx)
        return { add_modifier("own_active", "card.changing_shifts") }
    end,
}
