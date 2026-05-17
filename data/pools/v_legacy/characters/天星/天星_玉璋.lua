-- characters/天星/天星_玉璋.lua
-- 技能：消耗 5 AP，造成 2 岩伤害，获得 3 层玉璋护盾，召唤岩脊

local 天星 = get_char("天星")
local my_player = 天星:owner_player()
local my_char = 天星:owner_char()

local 岩脊_rounds = get_counter("岩脊_rounds", Scope.ActiveStatus)
local 玉璋护盾 = get_counter("玉璋护盾", Scope.ActiveStatus)
local 玉璋 = declare_skill(天星, "玉璋", { dices = { geo = 5 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 玉璋 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 2)
  玉璋护盾:add(3)

  -- 召唤岩脊（刷新时给护盾）
  if 岩脊_rounds:get() > 0 then
    玉璋护盾:add(1)
  end
  岩脊_rounds:set(2)
end)
