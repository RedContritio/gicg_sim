-- cards/支援/鸣神大社.lua
-- source: data/cleaned/action/6325_鸣神大社.yaml
-- 字段对照 (强制锁定):
--   id=6325 sub_class=支援牌 cost={同色:2}
--   effect: 我方角色使用技能后:如果元素骰总数为奇数,生成 1 个万能元素 (每回合 2 次, 可用次数 3)
-- deferred:
--   - 奇数骰条件检查 (本 lua 简化:技能后无条件 +1 万能, 每回合 2 次, 持续 3 回合)

local ref = declare_card("鸣神大社", { dices = { match = 2 } }, { slot = Slot.Support })
local rounds = declare_counter("鸣神大社_rounds", Scope.PerPlayer, 0, { min = 0, max = 3 })
local per_round = declare_counter("鸣神大社_per_round", Scope.PerPlayer, 0, { min = 0, max = 2 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  rounds:set_at(ctx.actor_player, 3)
end)

on_round_start(function(ctx)
  local p = context_player()
  if rounds:get_at(p) <= 0 then return end
  per_round:set_at(p, 2)
end)

on_round_end_decay(function(ctx)
  local p = context_player()
  if rounds:get_at(p) > 0 then
    rounds:set_at(p, rounds:get_at(p) - 1)
  end
end)

on_skill_use(function(ctx)
  if rounds:get_at(ctx.actor_player) <= 0 then return end
  if per_round:get_at(ctx.actor_player) <= 0 then return end
  add_dice(ctx.actor_player, DiceColor.Omni, 1)
  per_round:set_at(ctx.actor_player, per_round:get_at(ctx.actor_player) - 1)
end)
