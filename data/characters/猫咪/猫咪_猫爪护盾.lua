-- characters/猫咪/猫咪_猫爪护盾.lua
-- 技能：消耗 3 AP，造成 1 冰元素伤害，获得 2 点猫爪护盾（上限 4）

local 猫咪 = get_char("猫咪")
local 猫爪护盾 = declare_counter("猫爪护盾", Scope.ActiveStatus, 0, { min = 0, max = 4, tag = Tag.Shield })
local 猫爪 = declare_skill(猫咪, "猫爪护盾", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 猫爪 then return end
  deal_damage(Target.EnemyActive, Element.Ice, 1)
  猫爪护盾:add(2)
end)

on_damage_reduce(function(ctx)
  if ctx.target_player ~= 猫咪:owner_player() then return end
  if ctx.target_char ~= 猫咪:owner_char() then return end
  local shield = 猫爪护盾:get()
  if shield <= 0 then return end

  local absorb = min(shield, ctx.value)
  猫爪护盾:sub(absorb)
  ctx.value = ctx.value - absorb
end)
