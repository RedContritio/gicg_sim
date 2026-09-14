local fire = get_counter("火元素附着", Scope.PerChar)
local water = get_counter("水元素附着", Scope.PerChar)
local ice = get_counter("冰元素附着", Scope.PerChar)
local electro = get_counter("雷元素附着", Scope.PerChar)
local swirl = declare_reaction("Swirl")

on_reaction_damage(function(ctx)
  if ctx.element ~= Element.Anemo then return end
  local tp, tc = ctx.target_player, ctx.target_char
  local spread = Element.None
  if fire:get_at(tp, tc) > 0 then
    spread = Element.Fire
    fire:set_at(tp, tc, 0)
  elseif water:get_at(tp, tc) > 0 then
    spread = Element.Water
    water:set_at(tp, tc, 0)
  elseif ice:get_at(tp, tc) > 0 then
    spread = Element.Ice
    ice:set_at(tp, tc, 0)
  elseif electro:get_at(tp, tc) > 0 then
    spread = Element.Electro
    electro:set_at(tp, tc, 0)
  end
  if spread == Element.None then return end
  ctx.element = Element.None
  ctx.reaction_element = spread
  set_reaction_kind(swirl)
  if ctx.attachment_only then return end
  local victim = _char_by_slot[tp][tc]
  defer_fn(function()
    deal_damage(victim, spread, 1, { source = Source.Reaction, other_characters = true })
  end)
end)
