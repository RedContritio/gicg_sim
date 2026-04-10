-- characters/赤蝶/赤蝶_蝶火.lua
-- 技能：消耗 3 AP，对自己造成 1 穿透伤害，获得蝶火状态（2 回合）
-- 蝶火状态：火元素附魔，【枪】伤害 +2
-- 蝶火状态下【回火】：HP < 50% 额外治疗 (2 + 对方存活人数)

local 赤蝶 = get_char("赤蝶")
local 蝶火_active = declare_counter("蝶火_active", Scope.Self, 0, { min = 0, max = 1 })
local 蝶火_rounds = declare_counter("蝶火_rounds", Scope.Self, 0, { min = 0, max = 2 })

local 枪 = get_skill(赤蝶, "枪")
local 回火 = get_skill(赤蝶, "回火")

local 蝶火 = declare_skill(赤蝶, "蝶火", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 蝶火 then return end
  deal_damage(Target.OwnActive, Element.None, 1, { penetrate = true })
  蝶火_active:set(1)
  蝶火_rounds:set(2)
end)

on_damage_boost(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if 蝶火_active:get() > 0 and ctx.element == Element.Physical then
    ctx.element = Element.Fire
  end
end)

on_damage_boost(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if ctx.skill_index ~= 枪 then return end
  if 蝶火_active:get() > 0 then
    ctx.value = ctx.value + 2
  end
end)

on_after_damage(function(ctx)
  if ctx.skill_index ~= 回火 then return end
  if 蝶火_active:get() <= 0 then return end
  local hp = 赤蝶:hp():get()
  if hp < 赤蝶:hp():cmax() / 2 then
    local enemy_alive = get_counter("alive_count", Scope.PerPlayer, Player.Enemy)
    local enemy_count = enemy_alive:get()
    heal(Target.OwnActive, 2 + enemy_count)
  end
end)

on_round_end_decay(function(ctx)
  if 蝶火_active:get() > 0 then
    蝶火_rounds:sub(1)
    if 蝶火_rounds:get() <= 0 then
      蝶火_active:set(0)
    end
  end
end)
