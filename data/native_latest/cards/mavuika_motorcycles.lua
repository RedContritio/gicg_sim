card {
    id = "mavuika.motorcycle_leap",
    name = "驰轮车·跃升",
    description = "消耗1点夜魂值，造成4点火元素伤害。",
    tempo = "combat",
    cost = { dice = { any = 1 } },
    resolve = function(ctx)
        return {
            add_character_counter("mavuika", "nightsoul", -1),
            add_character_counter("mavuika", "fighting_spirit", 1),
            damage("enemy_active", "pyro", 4),
        }
    end,
}

card {
    id = "mavuika.motorcycle_traverse",
    name = "驰轮车·涉渡",
    description = "生成2个万能元素骰。",
    tempo = "fast",
    resolve = function(ctx)
        return { add_dice("omni", 2) }
    end,
}

card {
    id = "mavuika.motorcycle_sprint",
    name = "驰轮车·疾驰",
    description = "消耗1点夜魂值，生成2个万能元素骰。",
    tempo = "combat",
    cost = { dice = { any = 2 } },
    resolve = function(ctx)
        return {
            add_character_counter("mavuika", "nightsoul", -1),
            add_character_counter("mavuika", "fighting_spirit", 1),
            add_dice("omni", 2),
        }
    end,
}
