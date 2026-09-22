modifier {
    id = "alhaitham.chisel_light_mirror",
    name = "琢光镜",
    zone = "character",
    merge = "replace",
    counters = { rounds = { initial = 0, min = 0, max = 3 } },
    remove_at_zero = "rounds",
    damage = {
        direction = "outgoing",
        elements = { "physical" },
        set_element = "dendro",
        delta = 1,
    },
    handlers = {
        round_end = function(ctx)
            return { add_counter("source", "rounds", -1) }
        end,
    },
}

character {
    id = "alhaitham",
    name = "艾尔海森",
    element = "dendro",
    counters = {
        hp = { initial = 10, min = 0, max = 10 },
        energy = { initial = 0, min = 0, max = 2 },
    },
    actions = {
        {
            id = "abductive_reasoning",
            name = "溯因反绎法",
            cost = { dice = { dendro = 1, any = 2 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "physical", 2),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "universality_an_elaboration_on_form",
            name = "共相·理式摹写",
            cost = { dice = { dendro = 3 } },
            resolve = function(ctx)
                return {
                    damage("enemy_active", "dendro", 2),
                    add_modifier("actor", "alhaitham.chisel_light_mirror"),
                    add_modifier_counter("alhaitham.chisel_light_mirror", "rounds", 2),
                    add_counter("actor", "energy", 1),
                }
            end,
        },
        {
            id = "particular_field_fetters_of_phenomena",
            name = "殊境·显像缚结",
            cost = {
                dice = { dendro = 3 },
                counters = { { name = "energy", require = 2, consume = 2 } },
            },
            resolve = function(ctx)
                local rounds = ctx.modifier_counter("alhaitham.chisel_light_mirror", "rounds")
                local effects = { damage("enemy_active", "dendro", 4 + rounds) }
                if rounds > 0 then
                    effects[#effects + 1] = remove_modifier("alhaitham.chisel_light_mirror")
                end
                if rounds < 3 then
                    effects[#effects + 1] = add_modifier("actor", "alhaitham.chisel_light_mirror")
                    effects[#effects + 1] = add_modifier_counter(
                        "alhaitham.chisel_light_mirror", "rounds", 3 - rounds
                    )
                end
                return effects
            end,
        },
    },
}
