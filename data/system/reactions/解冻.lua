local frozen = get_counter("frozen", Scope.PerChar)

on_reaction_damage(10, function(ctx)
  if ctx.element ~= Element.Fire then return end
  local tp, tc = ctx.target_player, ctx.target_char
  if frozen:get_at(tp, tc) <= 0 then return end

  frozen:set_at(tp, tc, 0)
  ctx.value = ctx.value + 2
  ctx.element = Element.None
end)
