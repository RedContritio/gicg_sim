-- 最新官方快照天赋；装备后技能伤害使用技能来源，牌费用只支付一次。
local card = declare_card("冷血之剑", { dices = { ice = 3 }, energy = 0 }, { battle_action = true, requires_char = "凯亚" })
local character = get_char("凯亚")
local skill = get_skill(character, "霜袭")
local active = get_counter("冷血之剑_装备", Scope.Self)
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card then return end
  if get_active_char(ctx.actor_player) ~= character:owner_char() then ctx.playable = false end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  active:set(1)
  invoke_skill(skill, { source = Source.Skill })
end)
