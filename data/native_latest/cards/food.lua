modifier {
    id = "card.minty_meat_rolls",
    name = "薄荷兽肉卷",
    zone = "character",
    merge = "replace",
    counters = { uses = { initial = 3, min = 0, max = 3 } },
    remove_at_zero = "uses",
    action = {
        kinds = { "skill" },
        skills = { "normal_attack" },
        reduce_dice = 1,
        counter = "uses",
    },
    handlers = {},
}

card {
    id = "minty_meat_rolls",
    name = "薄荷兽肉卷",
    description = "目标角色接下来的3次普通攻击少花费1个元素骰。",
    kind = "event",
    tempo = "fast",
    cost = { dice = { any = 1 } },
    target = { side = "own", state = "alive" },
    resolve = function(ctx)
        return { add_modifier("target", "card.minty_meat_rolls") }
    end,
}
