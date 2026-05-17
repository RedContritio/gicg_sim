-- system/alive.lua
-- 维护每位玩家的"存活角色数"。
-- 初次登场 + 复活都走 on_revive；死亡走 on_death。
-- 完全基于 alive counter 的 0↔1 状态跃迁。

local alive_count = declare_counter("alive_count", Scope.PerPlayer, 0, { max = 10, display = "存活数" })

on_revive(function(ctx)
  alive_count:add_at(ctx.actor_player, 1)
end)

on_death(function(ctx)
  alive_count:sub_at(ctx.actor_player, 1)
end)
