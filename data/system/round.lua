local round_num = declare_counter("round_num", Scope.Global, 0, { min = 0, max = 999 })
local round1_first_player = declare_counter("round1_first_player", Scope.Global, -1, { min = -1, max = 1 })

on_round_start(function(ctx)
  if context_player() == 0 then
    round_num:add(1)
    if round_num:get() == 1 then
      round1_first_player:set(get_turn())
    end
  end
end)
