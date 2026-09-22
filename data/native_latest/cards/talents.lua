modifier {
    id = "talent.kaeya.cold_blooded_strike",
    name = "冷血之剑",
    zone = "character",
    slot = "talent",
    merge = "replace",
    counters = { uses = { initial = 1, min = 0, max = 1 } },
    handlers = {
        action_resolved = function(ctx)
            if ctx.actor_definition ~= "kaeya"
                or ctx.event.skill ~= "elemental_skill"
                or ctx.counter("source", "uses") == 0 then
                return nil
            end
            return {
                heal("actor", 2),
                add_counter("source", "uses", -1),
            }
        end,
        round_start = function(ctx)
            return { add_counter("source", "uses", 1) }
        end,
    },
}

card {
    id = "cold_blooded_strike",
    name = "冷血之剑",
    description = "装备此牌后，立即使用一次霜袭；此后每回合首次使用元素战技后治疗自身2点。",
    kind = "talent",
    tempo = "combat",
    cost = { dice = { cryo = 3 } },
    talent = { character = "kaeya", action = "frostgnaw" },
    resolve = function(ctx)
        return { add_modifier("own_active", "talent.kaeya.cold_blooded_strike") }
    end,
}
