-- system/draw.lua
-- 抽牌规则：每回合末抽 2 张
-- system hook 在 round_end_final 自动展开为每个玩家各 fire 一次

local DRAW_PER_ROUND = 2

on_round_end_final(function(ctx)
  draw_card_self(DRAW_PER_ROUND)
end)
