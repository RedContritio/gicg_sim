-- Match=2 cost. Effect is state-dependent on the caster side:
--   - If the caster has used ANY skill this round → deals 2 water
--     damage (Element.Water). On a fire-attached target this triggers
--     蒸发 via data/system/reactions/蒸发.lua:8, so the engine's
--     reaction pipeline adds +2 to make the final damage 4.
--   - Otherwise → deals 2 physical damage (no reaction possible).
--
-- The "used a skill this round" flag is a PerPlayer counter, set in
-- on_skill_use for the acting player, and reset in on_round_start
-- (fired once per player at round start by the engine, so each player's
-- flag resets to 0 for their own turn of the new round).
local ref = declare_card("测试卡_神秘水流", { dices = { match = 2 } })
local used_skill = declare_counter("神秘水流_used_skill", Scope.PerPlayer, 0, { min = 0, max = 1 })

on_skill_use(function(ctx)
  used_skill:set_at(ctx.actor_player, 1)
end)

on_round_start(function(ctx)
  used_skill:set(0)
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  if used_skill:get_at(ctx.actor_player) > 0 then
    deal_damage(Target.EnemyActive, Element.Water, 2)
  else
    deal_damage(Target.EnemyActive, Element.Physical, 2)
  end
end)
