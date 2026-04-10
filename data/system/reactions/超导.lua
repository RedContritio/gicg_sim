local attached_ice     = get_counter("attached_ice",     Scope.PerChar)
local attached_electro = get_counter("attached_electro", Scope.PerChar)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Electro and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Ice and attached_electro:get_at(tp, tc) > 0 then
    attached_electro:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    ctx.element = Element.None
    defer_fn(function()
      deal_damage(Target.EnemyAll, Element.None, 1, { penetrate = true, source = Source.Reaction })
    end)
  end
end)
