-- characters/猫咪/猫咪_甜美领域.lua
-- 大招：消耗 3 AP + 3 能量，造成 2 冰伤害，召唤甜美领域（持续 2 回合）
-- 甜美领域：回合结束时，治疗出战角色 2 HP，对敌方造成 1 冰伤害

local 猫咪 = get_char("猫咪")
local 甜美领域_rounds = declare_counter("甜美领域_rounds", Scope.ActiveStatus, 0, { min = 0, max = 2, tag = Tag.Summon })
local 甜美领域 = declare_skill(猫咪, "甜美领域", 3, 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 甜美领域 then return end
  deal_damage(Target.EnemyActive, Element.Ice, 2)
  甜美领域_rounds:set(2)
end)

on_round_end_post_summon(function(ctx)
  if 甜美领域_rounds:get() <= 0 then return end
  heal(Target.OwnActive, 2)
  deal_damage(Target.EnemyActive, Element.Ice, 1, { source = Source.Summon })
end)

on_round_end_decay(function(ctx)
  if 甜美领域_rounds:get() > 0 then
    甜美领域_rounds:sub(1)
  end
end)
