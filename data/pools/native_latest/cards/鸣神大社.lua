-- 最新官方快照6325：任意3；技能后骰数为奇数则加1万能，每回合2次，无持续回合限制。
local card = declare_card("鸣神大社", { dices = { any = 3 } }, { slot = Slot.Support })
local active = declare_counter("鸣神大社_在场", Scope.PerPlayer, 0, { min = 0, max = 1 })
register_buff(active, { independent = true })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  spawn_support_buff(active, 1, -1)
end)
on_round_start({ order = active }, function(ctx)
  set_buff_progress(0)
end)
on_skill_use({ order = active, priority = -30 }, function(ctx)
  if buff_progress() >= 2 then return end
  local total = get_dice_total(ctx.actor_player)
  -- DSL运算是整数除法；此表达式判断奇数。
  if total - total / 2 * 2 ~= 1 then return end
  set_buff_progress(buff_progress() + 1)
  add_dice(ctx.actor_player, DiceColor.Omni, 1)
end)
