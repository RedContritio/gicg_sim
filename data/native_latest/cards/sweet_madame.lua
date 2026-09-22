card {
    id = "sweet_madame",
    name = "甜甜花酿鸡",
    description = "治疗一个我方角色1点。",
    kind = "food",
    tempo = "fast",
    target = { side = "own", state = "alive", damaged = true },
    resolve = function(ctx)
        return { heal("target", 1) }
    end,
}
