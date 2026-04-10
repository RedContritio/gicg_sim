local round_num = get_counter("round_num", Scope.Global)
local round1_first_player = get_counter("round1_first_player", Scope.Global)
local alive = get_counter("alive_count", Scope.PerPlayer)

on_round_end_final(function(ctx)
  if round_num:get() < 10 then return end

  local own = alive:get()
  local enemy = alive:get_at(Player.Enemy)
  if own > enemy then
    set_winner(context_player())
  elseif own == enemy then
    if round1_first_player:get() ~= context_player() then
      set_winner(context_player())
    end
  end
end)
