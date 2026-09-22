card {
    id = "miscalculation",
    name = "失策",
    description = "对方随机弃置1张手牌。",
    kind = "event",
    tempo = "fast",
    cost = { dice = { any = 1 } },
    resolve = function(ctx)
        return { discard("enemy", 1) }
    end,
}

card {
    id = "send_off",
    name = "送你一程",
    description = "选择并移除一个对方召唤物。",
    kind = "event",
    tempo = "fast",
    cost = { dice = { any = 2 } },
    target = { kind = "summon", side = "enemy" },
    resolve = function(ctx)
        return { remove_target("target") }
    end,
}
