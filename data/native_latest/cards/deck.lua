card {
    id = "where_is_the_unseen_razor",
    name = "藏锋何处？",
    description = "从牌库中抽取1张旅行剑。",
    kind = "event",
    tempo = "fast",
    resolve = function(ctx)
        return { draw_card("travelers_handy_sword") }
    end,
}

card {
    id = "yesterdays_memory",
    name = "昨日重现",
    description = "从弃牌堆中取回1张水溅跃。",
    kind = "event",
    tempo = "fast",
    resolve = function(ctx)
        return { recover_card("splash") }
    end,
}

card {
    id = "backup_supplies",
    name = "备用物资",
    description = "将2张水溅跃洗入牌库，然后抽取1张水溅跃。",
    kind = "event",
    tempo = "fast",
    resolve = function(ctx)
        return {
            add_deck_card("splash", 2),
            draw_card("splash"),
        }
    end,
}
