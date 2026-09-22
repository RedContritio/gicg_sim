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

modifier {
    id = "card.when_the_crane_returned",
    name = "鹤归之时",
    zone = "combat",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    remove_at_zero = "uses",
    handlers = {
        action_resolved = function(ctx)
            if ctx.event.player ~= ctx.owner or ctx.event.action_kind ~= "skill" then
                return nil
            end
            return {
                switch_active("own"),
                add_counter("source", "uses", -1),
            }
        end,
    },
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

card {
    id = "when_the_crane_returned",
    name = "鹤归之时",
    description = "下一次使用技能后，将下一个后台角色切换到场上。",
    tempo = "fast",
    cost = { dice = { any = 1 } },
    resolve = function(ctx)
        return { add_modifier("own_active", "card.when_the_crane_returned") }
    end,
}
