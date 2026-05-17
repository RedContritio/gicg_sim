-- 消耗 2 同色 (Match=2, 玩家选色,omni 替代),下次 Skill 伤害 ×2。
-- buff 是 PerPlayer,任何本方角色下一次技能享受 (demo 简化)。consume
-- 条件: 1 次 SrcSkill 的 on_damage_boost 事件。中间穿插的 SrcCard
-- 伤害 (如 测试卡_碎片) 不消耗 buff。
local ref = declare_card("测试卡_增幅", { dices = { match = 2 } })
local buff = declare_counter("测试卡_增幅_buff", Scope.PerPlayer, 0, { min = 0, max = 1 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  buff:set_at(ctx.actor_player, 1)
end)

on_damage_mul(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if buff:get_at(ctx.actor_player) <= 0 then return end
  ctx.value = ctx.value * 2
  buff:set_at(ctx.actor_player, 0)
end)
