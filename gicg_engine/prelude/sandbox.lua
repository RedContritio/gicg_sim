function _make_sandbox_env()
  local env = setmetatable({}, { __index = _G })
  env._current_owner_player = _current_owner_player
  env._current_owner_char = _current_owner_char
  return env
end

function _load_file_sandboxed(path)
  local chunk, err = loadfile(path)
  if not chunk then error(err, 2) end
  local env = _make_sandbox_env()
  local saved_p = _current_owner_player
  local saved_c = _current_owner_char
  _current_owner_player = env._current_owner_player
  _current_owner_char = env._current_owner_char
  setfenv(chunk, env)
  chunk()
  _current_owner_player = saved_p
  _current_owner_char = saved_c
end

function _load_string_sandboxed(code)
  local chunk, err = loadstring(code)
  if not chunk then error(err, 2) end
  local env = _make_sandbox_env()
  local saved_p = _current_owner_player
  local saved_c = _current_owner_char
  _current_owner_player = env._current_owner_player
  _current_owner_char = env._current_owner_char
  setfenv(chunk, env)
  chunk()
  _current_owner_player = saved_p
  _current_owner_char = saved_c
end
