local function puppet(id, name)
    modifier {
        id = "chiori." .. id,
        name = name,
        zone = "summon",
        merge = "replace",
        counters = { uses = { initial = 2, min = 0, max = 2 } },
        remove_at_zero = "uses",
        handlers = {
            round_end = function(ctx)
                return {
                    damage("enemy_active", "geo", 1),
                    add_counter("source", "uses", -1),
                }
            end,
        },
    }
end

puppet("calm", "平静养神之袖")
puppet("easy", "轻松迎敌之袖")
puppet("closed", "闭目战斗之袖")
puppet("nothing", "无事发生之袖")
puppet("side_eye", "侧目睥睨之袖")
puppet("displeased", "不悦挥刀之袖")

character {
    id = "chiori",
    name = "千织",
    element = "geo",
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        energy = { initial = 0, min = 0, max = 2 },
    },
    actions = {
        {
            id = "weaving_blade",
            name = "心织刀流",
            cost = { dice = { geo = 1, any = 2 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "physical", 2),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "fluttering_hasode",
            name = "羽袖一触",
            cost = { dice = { geo = 3 } },
            resolve = function(ctx)
                return {
                    choose("summon", {
                        { id = "calm", label = "平静养神之袖" },
                        { id = "easy", label = "轻松迎敌之袖" },
                        { id = "closed", label = "闭目战斗之袖" },
                        { id = "nothing", label = "无事发生之袖" },
                        { id = "side_eye", label = "侧目睥睨之袖" },
                        { id = "displeased", label = "不悦挥刀之袖" },
                    }),
                    add_counter("actor", "energy", 1),
                }
            end,
            continue = {
                summon = function(ctx)
                    return { add_modifier("actor", "chiori." .. ctx.option) }
                end,
            },
        },
        {
            id = "hiyoku_twin_blades",
            name = "二刀之形·比翼",
            cost = {
                dice = { geo = 3 },
                counters = { { name = "energy", require = 2, consume = 2 } },
            },
            resolve = function(ctx)
                return { damage("enemy_active", "geo", 5) }
            end,
        },
    },
}
