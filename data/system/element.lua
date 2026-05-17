-- system/element.lua

local attached_fire    = declare_counter("火元素附着",    Scope.PerChar, 0, { min = 0, max = 1 })
local attached_water   = declare_counter("水元素附着",   Scope.PerChar, 0, { min = 0, max = 1 })
local attached_ice     = declare_counter("冰元素附着",     Scope.PerChar, 0, { min = 0, max = 1 })
local 雷元素附着 = declare_counter("雷元素附着", Scope.PerChar, 0, { min = 0, max = 1 })
local frozen           = declare_counter("冻结",           Scope.PerChar, 0, { min = 0, max = 10 })

-- 角色死亡时清除所有元素附着和冻结状态
on_death(function(ctx)
  attached_fire:set_at(ctx.actor_player, ctx.actor_char, 0)
  attached_water:set_at(ctx.actor_player, ctx.actor_char, 0)
  attached_ice:set_at(ctx.actor_player, ctx.actor_char, 0)
  雷元素附着:set_at(ctx.actor_player, ctx.actor_char, 0)
  frozen:set_at(ctx.actor_player, ctx.actor_char, 0)
end)
