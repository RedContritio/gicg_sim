_chars = {}
_char_by_slot = { [0] = {}, [1] = {} }

_current_owner_player = -1
_current_owner_char = -1

function declare_char(name, opts)
  local hp = declare_counter("hp", Scope.Self, opts.hp, { min = 0, max = opts.hp })
  local energy = declare_counter("energy", Scope.Self, 0, { min = 0, max = opts.max_energy })
  local weapon = opts.weapon or Weapon.None
  local char = {
    name = name,
    hp = hp,
    energy = energy,
    element = opts.element or Element.None,
    weapon = weapon,
    _skills = {},
  }
  _chars[name] = char

  return setmetatable({}, {
    __index = {
      hp = function() return hp end,
      energy = function() return energy end,
      alive = function() return hp:get() > 0 end,
      name = function() return name end,
      element = function() return opts.element or Element.None end,
      weapon = function() return weapon end,
      owner_player = function() return char.player_idx end,
      owner_char = function() return char.char_idx end,
    },
  })
end

local _alive_count = declare_counter("alive_count", Scope.PerPlayer, 0, { max = 10 })

local _hp_write_hooks = {}
local _energy_write_hooks = {}

function register_on_all_hp(op, fn)
  _hp_write_hooks[#_hp_write_hooks + 1] = { op = op, fn = fn }
  for p = 0, 1 do
    for _, c in pairs(_char_by_slot[p]) do
      _raw_on_before_write(c.hp, op, fn)
    end
  end
end

function register_on_all_energy(op, fn)
  _energy_write_hooks[#_energy_write_hooks + 1] = { op = op, fn = fn }
  for p = 0, 1 do
    for _, c in pairs(_char_by_slot[p]) do
      _raw_on_after_write(c.energy, op, fn)
    end
  end
end

function bind_char(name, player_idx, char_idx)
  local c = _chars[name]
  if not c then error("unknown char: " .. name, 2) end
  c.player_idx = player_idx
  c.char_idx = char_idx
  _char_by_slot[player_idx][char_idx] = c
  _current_owner_player = player_idx
  _current_owner_char = char_idx

  _register_counter_char(c.hp, player_idx, char_idx)
  _register_counter_char(c.energy, player_idx, char_idx)
  _alive_count:add_at(player_idx, 1)

  if c._skill_ids then
    for _, sid in ipairs(c._skill_ids) do
      _add_skill(player_idx, char_idx, sid)
    end
  end

  if register_death_check then
    register_death_check(c.hp, player_idx, char_idx)
  end

  for _, h in ipairs(_hp_write_hooks) do
    _raw_on_before_write(c.hp, h.op, h.fn)
  end

  for _, h in ipairs(_energy_write_hooks) do
    _raw_on_after_write(c.energy, h.op, h.fn)
  end
end

function get_char(name)
  local c = _chars[name]
  if not c then error("unknown char: " .. name, 2) end
  return setmetatable({}, {
    __index = {
      hp = function() return c.hp end,
      energy = function() return c.energy end,
      alive = function() return c.hp:get() > 0 end,
      name = function() return name end,
      element = function() return c.element end,
      weapon = function() return c.weapon end,
      owner_player = function() return c.player_idx end,
      owner_char = function() return c.char_idx end,
    },
  })
end
