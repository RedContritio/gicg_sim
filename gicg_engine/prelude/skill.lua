local _next_skill_id = 0

function declare_skill(char_ref, skill_name, ap_cost, energy_cost, opts)
  energy_cost = energy_cost or 0
  opts = opts or {}
  local battle_action = opts.battle_action
  if battle_action == nil then battle_action = true end

  local char_name = char_ref:name()
  local c = _chars[char_name]
  if not c then error("unknown char: " .. char_name, 2) end

  local existing = c._skills[skill_name]
  if existing then
    if existing.ap_cost ~= ap_cost or existing.energy_cost ~= energy_cost
       or existing.battle_action ~= battle_action then
      error("declare_skill conflict for '" .. char_name .. ":" .. skill_name
            .. "': params differ from first declaration", 2)
    end
    return existing.id
  end

  local id = _next_skill_id
  _next_skill_id = id + 1
  c._skills[skill_name] = {
    id = id,
    ap_cost = ap_cost,
    energy_cost = energy_cost,
    battle_action = battle_action,
  }
  c._skill_ids = c._skill_ids or {}
  c._skill_ids[#c._skill_ids + 1] = id

  if c.player_idx then
    _add_skill(c.player_idx, c.char_idx, id)
  end

  on_action_check(function(ctx)
    if ctx.action_kind ~= ActionKind.Skill then return end
    if ctx.skill_index ~= id then return end
    if energy_cost > 0 and char_ref:energy():get() < energy_cost then
      ctx.playable = false
    end
  end)

  on_action_prepare(function(ctx)
    if ctx.action_kind ~= ActionKind.Skill then return end
    if ctx.skill_index ~= id then return end
    ctx.ap_cost = ap_cost
    ctx.energy_cost = energy_cost
    ctx.battle_action = battle_action
  end)

  on_skill_use(function(ctx)
    if ctx.skill_index ~= id then return end
    if ctx.paid then return end
    local ap = get_counter("ap", Scope.PerPlayer)
    ap:sub(ap_cost)
    if energy_cost > 0 then
      consume_energy(char_ref:energy(), energy_cost)
    end
  end)

  if energy_cost == 0 then
    on_after_damage(function(ctx)
      if ctx.source ~= Source.Skill then return end
      if ctx.skill_index ~= id then return end
      if not ctx.hit then return end
      gain_energy(char_ref:energy(), 1)
    end)
  end

  return id
end

function get_skill(char_ref, skill_name)
  local char_name = char_ref:name()
  local c = _chars[char_name]
  if not c then error("unknown char: " .. char_name, 2) end
  local existing = c._skills[skill_name]
  if not existing then
    error("unresolved_dependency:" .. char_name .. ":" .. skill_name, 2)
  end
  return existing.id
end

function invoke_skill(skill_id)
  _invoke_skill(skill_id)
end

function gain_energy(energy_counter, value)
  _gain_energy(energy_counter, value)
end

function consume_energy(energy_counter, value)
  _consume_energy(energy_counter, value)
end
