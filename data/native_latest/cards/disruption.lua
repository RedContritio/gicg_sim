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
