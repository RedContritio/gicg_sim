local ref = declare_card("以逸待劳", { dices = { any = 8 } }, { battle_action = true })
local active = declare_counter("以逸待劳_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- 回合开始:生成 2 个当前出战角色元素的骰子(原 +2 AP 效果随 AP 系统
-- 整体删除后改写;不用万能骰以制衡强度)。Element 与 DiceColor 两枚举
-- 不对齐(Element.None 占 0 位),必须经 element_to_dice_color 转换。
on_round_start({ order = active }, function(ctx)
  if active:get() <= 0 then return end
  local p = context_player()
  local c = _char_by_slot[p][get_active_char(p)]
  add_dice(p, element_to_dice_color(c.element), 2)
end)

-- 治疗事件请求量包含过量治疗。反击归属于支援所属一方，目标相对该方解析。
on_after_heal({ order = active, order_on = "target" }, function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  if ctx.value <= 0 then return end
  local p = ctx.target_player
  local c = _char_by_slot[p][get_active_char(p)]
  deal_damage(Target.EnemyActive, c.element, ctx.value, { source = Source.Support, actor = c })
end)

-- 减伤反击归属支援持有方。
on_after_damage({ order = active, order_on = "target" }, function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  if ctx.absorbed <= 0 then return end
  local p = ctx.target_player
  local c = _char_by_slot[p][get_active_char(p)]
  deal_damage(Target.EnemyActive, c.element, ctx.absorbed, { source = Source.Support, actor = c })
end)

register_buff(active)
