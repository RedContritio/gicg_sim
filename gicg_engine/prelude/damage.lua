function context_player()
  return _current_context_player
end

function draw_card_self(count)
  draw_card(_current_context_player, count)
end

-- Wrap Go callbacks to accept Player constants
local _raw_get_active_char = get_active_char
get_active_char = function(p) return _raw_get_active_char(_resolve_p(p)) end

function set_active_char(p, c)
  _set_active_char(_resolve_p(p), c)
end

local _raw_force_switch_next = force_switch_next
force_switch_next = function(p) _raw_force_switch_next(_resolve_p(p)) end

_current_card_target_player = -1
_current_card_target_char = -1

local function _hp_at(p, c)
  local ch = _char_by_slot[p][c]
  if ch then return ch.hp end
  return nil
end

local function resolve_target_hp(target)
  local actor = get_actor_player()
  local enemy = 1 - actor
  if target == Target.EnemyActive then
    return _hp_at(enemy, get_active_char(enemy))
  elseif target == Target.OwnActive then
    return _hp_at(actor, get_active_char(actor))
  elseif target == Target.CardTarget then
    return _hp_at(_current_card_target_player, _current_card_target_char)
  elseif target == Target.EnemyAll or target == Target.EnemyNonActive then
    local active = get_active_char(enemy)
    local result = {}
    for ci = 0, MAX_CHARS - 1 do
      local c = _char_by_slot[enemy][ci]
      if c and c.hp:get() > 0 then
        if target == Target.EnemyAll or ci ~= active then
          result[#result + 1] = c.hp
        end
      end
    end
    return result
  elseif target == Target.OwnAll then
    local result = {}
    for ci = 0, MAX_CHARS - 1 do
      local c = _char_by_slot[actor][ci]
      if c and c.hp:get() > 0 then
        result[#result + 1] = c.hp
      end
    end
    return result
  end
  return target
end

function deal_damage(target, element, value, opts)
  opts = opts or {}
  local resolved = resolve_target_hp(target)
  if type(resolved) == "table" then
    for _, hp in ipairs(resolved) do
      _raw_deal_damage(hp, element, value, opts)
    end
  else
    _raw_deal_damage(resolved, element, value, opts)
  end
end

function heal(target, value)
  local resolved = resolve_target_hp(target)
  if type(resolved) == "table" then
    for _, hp in ipairs(resolved) do
      _raw_heal(hp, value)
    end
  else
    _raw_heal(resolved, value)
  end
end
