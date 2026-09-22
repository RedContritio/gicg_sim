card {
    id = "strategize",
    name = "运筹帷幄",
    description = "抽2张牌。",
    tempo = "fast",
    cost = { dice = { any = 1 } },
    resolve = function(ctx)
        return { draw(2) }
    end,
}
