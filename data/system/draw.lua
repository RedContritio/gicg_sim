-- system/draw.lua
-- 抽牌规则：
--   - 第 1 回合开始：双方各抽 5 张作为初始手牌
--   - 每回合末：双方各抽 2 张
-- system hook 自动展开为每个玩家各 fire 一次

local DRAW_PER_ROUND = 2
local INITIAL_HAND = 5

local round_num = get_counter("round_num", Scope.Global)

on_round_start(function(ctx)
  if round_num:get() == 1 then
    draw_card(Player.Own, INITIAL_HAND)
  end
end)

on_round_end_final(function(ctx)
  draw_card(Player.Own, DRAW_PER_ROUND)
end)
