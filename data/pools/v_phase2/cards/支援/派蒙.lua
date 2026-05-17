-- cards/支援/派蒙.lua
-- source: data/cleaned/action/5448_派蒙.yaml
-- 字段对照 (强制锁定):
--   id=5448 sub_class=支援牌 cost={同色:3}
--   effect: 行动阶段开始时:生成 2 点万能元素 (可用次数 2, 用完弃置)
-- 用尽 2 次后调 remove_support 真退槽 + 进 Discard。
-- engine 侧 PlayerState.Supports + MaxSupportSlots=4 + HookSupportRemove。

local ref = declare_card("派蒙", { dices = { match = 3 } }, { slot = Slot.Support })
local active = declare_counter("派蒙_active", Scope.PerPlayer, 0, { min = 0, max = 2 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set_at(ctx.actor_player, 2)
end)

on_round_start(function(ctx)
  local p = context_player()
  if active:get_at(p) <= 0 then return end
  add_dice(p, DiceColor.Omni, 2)
  local left = active:get_at(p) - 1
  active:set_at(p, left)
  if left <= 0 then
    remove_support(p, ref)
  end
end)
