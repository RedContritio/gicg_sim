-- cards/装备/旅行剑.lua
-- source: data/cleaned/action/5418_旅行剑.yaml
-- 字段对照 (强制锁定):
--   id=5418 sub_class=装备牌 cost={同色:2} requires_weapon=单手剑
--   effect: 角色造成的伤害+1
-- deferred:
--   - talent 武器原版还有 "如果有充能,普攻造成伤害+1 / 取消减伤" 等条件 buff (本 lua 只做 +1 基础)

local ref = declare_card("旅行剑", { dices = { match = 2 } }, { target = "own", requires_weapon = Weapon.Sword })
local equipped = get_counter("equipped", Scope.PerChar)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  if not c or c.weapon ~= Weapon.Sword then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  equipped:set_at(ctx.target_player, ctx.target_char, ref)
end)

on_damage_add(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  ctx.value = ctx.value + 1
end)
