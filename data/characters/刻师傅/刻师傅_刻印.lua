-- characters/刻师傅/刻师傅_刻印.lua
-- 技能：消耗 3 AP，造成 3 雷元素伤害
-- 获得 1 回合雷附魔，本回合剑伤害 +1
-- 获得 1 张复刻手牌（同时只能持有 1 张）

local 刻师傅 = get_char("刻师傅")
local 刻印_enchant = declare_counter("刻印_enchant", Scope.Self, 0, { min = 0, max = 1 })
local 刻印_sword_buff = declare_counter("刻印_sword_buff", Scope.Self, 0, { min = 0, max = 1 })
local 复刻_mode = declare_counter("复刻_mode", Scope.Self, 0, { min = 0, max = 1 })
local 复刻_in_hand = declare_counter("复刻_in_hand", Scope.PerPlayer, 0, { min = 0, max = 1 })

local 剑 = get_skill(刻师傅, "剑")
local 刻印 = declare_skill(刻师傅, "刻印", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 刻印 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 3)
  if 复刻_mode:get() > 0 then
    复刻_mode:set(0)
    return
  end
  刻印_enchant:set(1)
  刻印_sword_buff:set(1)
  if 复刻_in_hand:get() <= 0 then
    local 复刻_ref = get_card("复刻")
    add_card(复刻_ref, Zone.Hand)
    复刻_in_hand:set(1)
  end
end)

on_damage_boost(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if ctx.actor_player ~= 刻师傅:owner_player() then return end
  if 刻印_enchant:get() > 0 and ctx.element == Element.Physical then
    ctx.element = Element.Electro
  end
end)

on_damage_boost(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if ctx.skill_index ~= 剑 then return end
  if 刻印_sword_buff:get() > 0 then
    ctx.value = ctx.value + 1
  end
end)

on_round_end_decay(function(ctx)
  刻印_enchant:set(0)
  刻印_sword_buff:set(0)
end)
