local attached_ice     = get_counter("冰元素附着",     Scope.PerChar)
local 雷元素附着 = get_counter("雷元素附着", Scope.PerChar)

local R_SUPERCONDUCT = declare_reaction("Superconduct")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Electro and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Ice and 雷元素附着:get_at(tp, tc) > 0 then
    雷元素附着:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    ctx.value = ctx.value + 1
    ctx.element = Element.None
    set_reaction_kind(R_SUPERCONDUCT)
    if ctx.attachment_only then return end
    local victim = _char_by_slot[tp][tc]
    defer_fn(function()
      deal_damage(victim, Element.Piercing, 1, { source = Source.Reaction, other_characters = true })
    end)
  end
end)
