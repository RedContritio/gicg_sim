-- characters/刻师傅/刻师傅_刻印.lua
-- 技能：消耗 3 AP，造成 3 雷元素伤害
-- 刻师傅获得 1 回合雷元素附魔（本角色的物理伤害转为雷伤害）
-- 刻师傅本回合的剑伤害 +1
-- 使用后生成 1 张复刻手牌（由 刻师傅_复刻.lua 处理）

local 刻师傅 = get_char("刻师傅")
local my_player = 刻师傅:owner_player()
local my_char = 刻师傅:owner_char()

local 刻印_雷元素附魔 = declare_counter("刻印_雷元素附魔", Scope.Self, 0, { min = 0, max = 1 })
local 刻印_剑伤害加成 = declare_counter("刻印_剑伤害加成", Scope.Self, 0, { min = 0, max = 1 })

local 剑 = get_skill(刻师傅, "剑")
local 刻印 = declare_skill(刻师傅, "刻印", { dices = { electro = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 刻印 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 3)
  -- 复刻触发的刻印（ctx.source 为 Card）：只造成伤害，不获得附魔/buff
  if ctx.source == Source.Card then return end
  刻印_雷元素附魔:set(1)
  刻印_剑伤害加成:set(1)
end)

on_damage_type(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.source ~= Source.Skill then return end
  if 刻印_雷元素附魔:get() > 0 and ctx.element == Element.Physical then
    ctx.element = Element.Electro
  end
end)

on_damage_add(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.source ~= Source.Skill then return end
  if ctx.skill_index ~= 剑 then return end
  if 刻印_剑伤害加成:get() > 0 then
    ctx.value = ctx.value + 1
  end
end)

on_round_end_decay(function(ctx)
  刻印_雷元素附魔:set(0)
  刻印_剑伤害加成:set(0)
end)
