local 雷元素附着 = get_counter("雷元素附着", Scope.PerChar)
local attached_fire    = get_counter("火元素附着",    Scope.PerChar)

local R_OVERLOAD = declare_reaction("Overload")  -- ADR-0019 §B.3
local pending_switch = declare_counter("超载_待切换", Scope.PerChar, 0, { min = 0, max = 1 })

-- Provisional B17: lethal overload selects the next living character too.
-- Switching during the death callback prevents the generic death handler from
-- queuing a second, player-selected replacement for the old active character.
on_death(function(ctx)
  local p, c = ctx.actor_player, ctx.actor_char
  if pending_switch:get_at(p, c) > 0 then
    pending_switch:set_at(p, c, 0)
    if get_active_char(p) == c then force_switch_next(p) end
  end
end)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local was_active = tc == get_active_char(tp)
  local triggered = false

  if ctx.element == Element.Fire and 雷元素附着:get_at(tp, tc) > 0 then
    雷元素附着:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Electro and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    if was_active then pending_switch:set_at(tp, tc, 1) end
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_OVERLOAD)
    defer_fn(function()
      -- A background reaction must not switch an unrelated active character.
      pending_switch:set_at(tp, tc, 0)
      if was_active and is_char_alive(tp, tc) and get_active_char(tp) == tc then
        force_switch_next(tp)
      end
    end)
  end
end)
