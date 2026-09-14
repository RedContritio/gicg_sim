local frozen = get_counter("冻结", Scope.PerChar)

local R_SHATTER = declare_reaction("Shatter")  -- ADR-0019 §B.3 (碎冰/解冻)

on_reaction_damage(10, function(ctx)
  if ctx.element ~= Element.Fire and ctx.element ~= Element.Physical then return end
  local tp, tc = ctx.target_player, ctx.target_char
  if frozen:get_at(tp, tc) <= 0 then return end

  frozen:set_at(tp, tc, 0)
  ctx.value = ctx.value + 2
  ctx.element = Element.None
  set_reaction_kind(R_SHATTER)
end)
