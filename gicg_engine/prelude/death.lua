function register_death_check(hp_counter, player_idx, char_idx)
  local alive = get_counter("alive_count", Scope.PerPlayer)
  on_after_write(hp_counter, Op.Sub, function(ctx)
    if hp_counter:get() > 0 then return end
    set_alive(player_idx, char_idx, false)
    alive:sub_at(player_idx, 1)
    local ok, af = pcall(get_counter, "attached_fire", Scope.PerChar)
    if ok then
      af:set_at(player_idx, char_idx, 0)
      get_counter("attached_water",   Scope.PerChar):set_at(player_idx, char_idx, 0)
      get_counter("attached_ice",     Scope.PerChar):set_at(player_idx, char_idx, 0)
      get_counter("attached_electro", Scope.PerChar):set_at(player_idx, char_idx, 0)
      get_counter("frozen",           Scope.PerChar):set_at(player_idx, char_idx, 0)
    end
    request_switch(player_idx)
  end)
end
