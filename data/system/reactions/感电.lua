local attached_electro = get_counter("attached_electro", Scope.PerChar)
local attached_water   = get_counter("attached_water",   Scope.PerChar)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Water and attached_electro:get_at(tp, tc) > 0 then
    attached_electro:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Electro and attached_water:get_at(tp, tc) > 0 then
    attached_water:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    ctx.element = Element.None
    defer_fn(function()
      deal_damage(Target.EnemyAll, Element.None, 1, { penetrate = true, source = Source.Reaction })
    end)
  end
end)
