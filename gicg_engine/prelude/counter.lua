min = math.min
max = math.max

local function _register_write_hook(raw_fn, counter_or_proxy, op, fn)
  if type(counter_or_proxy) == "table" and counter_or_proxy._counters then
    local ids = {}
    for _, c in pairs(counter_or_proxy._counters) do
      ids[#ids + 1] = raw_fn(c, op, fn)
    end
    return ids
  end
  return raw_fn(counter_or_proxy, op, fn)
end

function on_before_write(counter, op, fn)
  return _register_write_hook(_raw_on_before_write, counter, op, fn)
end

function on_after_write(counter, op, fn)
  return _register_write_hook(_raw_on_after_write, counter, op, fn)
end

_current_context_player = -1

local _counter_registry = {}
local _tag_groups = {}

MAX_CHARS = 3

-- ========== Player resolution ==========

function _resolve_p(p)
  if p >= 0 then return p end
  if p == Player.Own then return _current_context_player end
  if p == Player.Enemy then return 1 - _current_context_player end
  error("invalid player value", 3)
end

-- ========== PerPlayer ==========

local _per_player_mt = {
  __index = {
    get = function(self)
      return self._counters[_current_context_player]:get()
    end,
    cmin = function(self)
      return self._counters[0]:cmin()
    end,
    cmax = function(self)
      return self._counters[0]:cmax()
    end,
    set = function(self, v)
      self._counters[_current_context_player]:set(v)
    end,
    add = function(self, v)
      self._counters[_current_context_player]:add(v)
    end,
    sub = function(self, v)
      self._counters[_current_context_player]:sub(v)
    end,
    get_at = function(self, p)
      return self._counters[_resolve_p(p)]:get()
    end,
    set_at = function(self, p, v)
      self._counters[_resolve_p(p)]:set(v)
    end,
    add_at = function(self, p, v)
      self._counters[_resolve_p(p)]:add(v)
    end,
    sub_at = function(self, p, v)
      self._counters[_resolve_p(p)]:sub(v)
    end,
  },
}

-- PerPlayer bound view: get()/set() resolve a Player constant dynamically
local _per_player_view_mt = {
  __index = {
    get = function(self)
      return self._inner._counters[_resolve_p(self._bind)]:get()
    end,
    cmin = function(self)
      return self._inner._counters[0]:cmin()
    end,
    cmax = function(self)
      return self._inner._counters[0]:cmax()
    end,
    set = function(self, v)
      self._inner._counters[_resolve_p(self._bind)]:set(v)
    end,
    add = function(self, v)
      self._inner._counters[_resolve_p(self._bind)]:add(v)
    end,
    sub = function(self, v)
      self._inner._counters[_resolve_p(self._bind)]:sub(v)
    end,
  },
}

-- ========== PerChar ==========

local _per_char_mt = {
  __index = {
    get = function(self)
      return self._counters[_current_context_player * MAX_CHARS + _current_owner_char]:get()
    end,
    cmin = function(self)
      return self._counters[0]:cmin()
    end,
    cmax = function(self)
      return self._counters[0]:cmax()
    end,
    set = function(self, v)
      self._counters[_current_context_player * MAX_CHARS + _current_owner_char]:set(v)
    end,
    add = function(self, v)
      self._counters[_current_context_player * MAX_CHARS + _current_owner_char]:add(v)
    end,
    sub = function(self, v)
      self._counters[_current_context_player * MAX_CHARS + _current_owner_char]:sub(v)
    end,
    get_at = function(self, p, c)
      return self._counters[_resolve_p(p) * MAX_CHARS + c]:get()
    end,
    set_at = function(self, p, c, v)
      self._counters[_resolve_p(p) * MAX_CHARS + c]:set(v)
    end,
    add_at = function(self, p, c, v)
      self._counters[_resolve_p(p) * MAX_CHARS + c]:add(v)
    end,
    sub_at = function(self, p, c, v)
      self._counters[_resolve_p(p) * MAX_CHARS + c]:sub(v)
    end,
    decay_all = function(self, p)
      local rp = _resolve_p(p)
      for c = 0, MAX_CHARS - 1 do
        local ctr = self._counters[rp * MAX_CHARS + c]
        if ctr:get() > 0 then ctr:sub(1) end
      end
    end,
    fill_all = function(self, p, v)
      local rp = _resolve_p(p)
      for c = 0, MAX_CHARS - 1 do
        self._counters[rp * MAX_CHARS + c]:set(v)
      end
    end,
  },
}

-- ========== Counter key & registry ==========

local function _counter_key(name, scope)
  if scope == Scope.PerPlayer or scope == Scope.PerChar or scope == Scope.Global then
    return name
  end
  return tostring(_current_owner_player) .. ":" .. tostring(_current_owner_char) .. ":" .. name
end

function declare_counter(name, scope, value, opts)
  opts = opts or {}
  local cmin = opts.min or 0
  local cmax = opts.max or 255

  local key = _counter_key(name, scope)
  local existing = _counter_registry[key]
  if existing then
    if existing.min ~= cmin or existing.max ~= cmax or existing.value ~= value or existing.scope ~= scope then
      error("declare_counter conflict for '" .. name .. "': params differ", 2)
    end
    return existing.ref
  end

  local ref
  if scope == Scope.PerPlayer then
    local counters = {}
    for p = 0, 1 do
      counters[p] = _raw_create_counter(value, cmin, cmax)
    end
    ref = setmetatable({ _counters = counters, _scope = scope }, _per_player_mt)
  elseif scope == Scope.PerChar then
    local counters = {}
    for i = 0, 2 * MAX_CHARS - 1 do
      counters[i] = _raw_create_counter(value, cmin, cmax)
    end
    ref = setmetatable({ _counters = counters, _scope = scope }, _per_char_mt)
  else
    ref = _raw_create_counter(value, cmin, cmax)
  end

  local tag = opts.tag
  local entry = {
    ref = ref, min = cmin, max = cmax, value = value,
    scope = scope, tag = tag,
    owner_player = _current_owner_player,
    owner_char = _current_owner_char,
  }
  _counter_registry[key] = entry

  if tag then
    _tag_groups[tag] = _tag_groups[tag] or {}
    _tag_groups[tag][#_tag_groups[tag] + 1] = entry
  end

  return ref
end

function get_counter(name, scope, bind)
  local key = _counter_key(name, scope)
  local existing = _counter_registry[key]
  if not existing then
    error("unresolved_dependency:" .. name, 2)
  end
  local ref = existing.ref
  if bind and type(ref) == "table" and ref._counters then
    return setmetatable({ _inner = ref, _bind = bind }, _per_player_view_mt)
  end
  return ref
end

-- ========== get_counter_group ==========

local function _group_iter_players(filter)
  local fp = filter and filter.player
  if fp == nil or fp == Player.Own then
    local p = _current_context_player
    return p, p
  elseif fp == Player.Enemy then
    local p = 1 - _current_context_player
    return p, p
  elseif fp == Player.All then
    return 0, 1
  elseif fp >= 0 then
    return fp, fp
  end
  error("invalid player filter", 3)
end

local function _entry_matches(e, p_lo, p_hi)
  if e.owner_player < 0 then return true end
  return e.owner_player >= p_lo and e.owner_player <= p_hi
end

local function _group_count(ref, scope, p_lo, p_hi)
  local n = 0
  if type(ref) == "table" and ref._counters then
    if scope == Scope.PerChar then
      for p = p_lo, p_hi do
        for c = 0, MAX_CHARS - 1 do
          if ref._counters[p * MAX_CHARS + c]:get() > 0 then n = n + 1 end
        end
      end
    elseif scope == Scope.PerPlayer then
      for p = p_lo, p_hi do
        if ref._counters[p]:get() > 0 then n = n + 1 end
      end
    end
  else
    if ref:get() > 0 then n = n + 1 end
  end
  return n
end

local function _group_set(ref, scope, p_lo, p_hi, v)
  if type(ref) == "table" and ref._counters then
    if scope == Scope.PerChar then
      for p = p_lo, p_hi do
        for c = 0, MAX_CHARS - 1 do
          local ctr = ref._counters[p * MAX_CHARS + c]
          if ctr:get() > 0 then ctr:set(v) end
        end
      end
    elseif scope == Scope.PerPlayer then
      for p = p_lo, p_hi do
        local ctr = ref._counters[p]
        if ctr:get() > 0 then ctr:set(v) end
      end
    end
  else
    if ref:get() > 0 then ref:set(v) end
  end
end

local function _group_add(ref, scope, p_lo, p_hi, delta)
  if type(ref) == "table" and ref._counters then
    if scope == Scope.PerChar then
      for p = p_lo, p_hi do
        for c = 0, MAX_CHARS - 1 do
          local ctr = ref._counters[p * MAX_CHARS + c]
          if ctr:get() > 0 then ctr:add(delta) end
        end
      end
    elseif scope == Scope.PerPlayer then
      for p = p_lo, p_hi do
        local ctr = ref._counters[p]
        if ctr:get() > 0 then ctr:add(delta) end
      end
    end
  else
    if ref:get() > 0 then ref:add(delta) end
  end
end

local function _group_sub(ref, scope, p_lo, p_hi, delta)
  if type(ref) == "table" and ref._counters then
    if scope == Scope.PerChar then
      for p = p_lo, p_hi do
        for c = 0, MAX_CHARS - 1 do
          local ctr = ref._counters[p * MAX_CHARS + c]
          if ctr:get() > 0 then ctr:sub(delta) end
        end
      end
    elseif scope == Scope.PerPlayer then
      for p = p_lo, p_hi do
        local ctr = ref._counters[p]
        if ctr:get() > 0 then ctr:sub(delta) end
      end
    end
  else
    if ref:get() > 0 then ref:sub(delta) end
  end
end

local _group_mt = {
  __index = {
    get = function(self)
      local p = _current_context_player
      local n = 0
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p, p) then
          n = n + _group_count(e.ref, e.scope, p, p)
        end
      end
      return n
    end,
    set = function(self, v)
      local p = _current_context_player
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p, p) then
          _group_set(e.ref, e.scope, p, p, v)
        end
      end
    end,
    add = function(self, v)
      local p = _current_context_player
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p, p) then
          _group_add(e.ref, e.scope, p, p, v)
        end
      end
    end,
    sub = function(self, v)
      local p = _current_context_player
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p, p) then
          _group_sub(e.ref, e.scope, p, p, v)
        end
      end
    end,
    get_at = function(self, f)
      local p_lo, p_hi = _group_iter_players(f)
      local n = 0
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p_lo, p_hi) then
          n = n + _group_count(e.ref, e.scope, p_lo, p_hi)
        end
      end
      return n
    end,
    set_at = function(self, f, v)
      local p_lo, p_hi = _group_iter_players(f)
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p_lo, p_hi) then
          _group_set(e.ref, e.scope, p_lo, p_hi, v)
        end
      end
    end,
    add_at = function(self, f, v)
      local p_lo, p_hi = _group_iter_players(f)
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p_lo, p_hi) then
          _group_add(e.ref, e.scope, p_lo, p_hi, v)
        end
      end
    end,
    sub_at = function(self, f, v)
      local p_lo, p_hi = _group_iter_players(f)
      for _, e in ipairs(self._entries) do
        if _entry_matches(e, p_lo, p_hi) then
          _group_sub(e.ref, e.scope, p_lo, p_hi, v)
        end
      end
    end,
  },
}

function get_counter_group(tag)
  local entries = _tag_groups[tag] or {}
  return setmetatable({ _entries = entries }, _group_mt)
end

function register_on_tag_write(tag, hook_type, op, fn)
  local raw_fn = hook_type == "before" and _raw_on_before_write or _raw_on_after_write
  local entries = _tag_groups[tag] or {}
  for _, e in ipairs(entries) do
    local ref = e.ref
    _register_write_hook(raw_fn, ref, op, function(ctx)
      fn(ctx, ref)
    end)
  end
end

create_counter = declare_counter
