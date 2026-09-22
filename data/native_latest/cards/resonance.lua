card {
    id = "thunder_and_eternity",
    name = "雷与永恒",
    description = "将我方所有元素骰转换为万能元素。",
    kind = "event",
    tempo = "fast",
    deck = { tags = { inazuma = 2 } },
    resolve = function(ctx)
        return { convert_dice("omni") }
    end,
}
