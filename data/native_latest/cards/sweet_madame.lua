card {
    id = "sweet_madame",
    name = "甜甜花酿鸡",
    description = "治疗一个我方角色1点。",
    tempo = "fast",
    resolve = function(ctx)
        return { choose_character("target") }
    end,
    continue = {
        target = function(ctx)
            return { heal("own_option", 1) }
        end,
    },
}
