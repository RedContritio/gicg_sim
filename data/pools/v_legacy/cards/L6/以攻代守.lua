local ref = declare_card("以攻代守", { dices = { any = 4 } })
local active = declare_counter("以攻代守_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

register_on_tag_write(Tag.Shield, "after", Op.Add, function(ctx, shield_ref)
  if active:get() <= 0 then return end
  local current = shield_ref:get()
  if current > 1 then
    local overflow = current - 1
    shield_ref:set(1)
    deal_damage(Target.EnemyActive, Element.Piercing, overflow, { source = Source.Support })
  end
end)
