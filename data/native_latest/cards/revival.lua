card {
    id = "teyvat_fried_egg",
    name = "提瓦特煎蛋",
    description = "复苏一个倒下的我方角色，并治疗其3点。",
    kind = "food",
    tempo = "fast",
    cost = { dice = { any = 3 } },
    target = { side = "own", state = "defeated" },
    resolve = function(ctx)
        return { revive("target", 3) }
    end,
}
