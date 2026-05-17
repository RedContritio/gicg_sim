-- characters/天星/天星_岩脊.lua
-- 技能：消耗 3 AP，造成 1 岩伤害，召唤岩脊（持续 2 回合）
-- 岩脊：回合结束时对敌方造成 1 岩伤害
-- 岩脊被刷新或销毁时，己方获得 1 层玉璋护盾

local 天星 = get_char("天星")
local my_player = 天星:owner_player()
local my_char = 天星:owner_char()

local 岩脊_rounds = declare_counter("岩脊_rounds", Scope.ActiveStatus, 0, { min = 0, max = 2, tag = Tag.Summon })
local 玉璋护盾 = declare_counter("玉璋护盾", Scope.ActiveStatus, 0, { min = 0, max = 5, tag = Tag.Shield })
local 岩脊 = declare_skill(天星, "岩脊", { dices = { geo = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 岩脊 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 1)

  if 岩脊_rounds:get() > 0 then
    玉璋护盾:add(1)
  end
  岩脊_rounds:set(2)
end)

-- PerPlayerHooks 已经针对 OwnerPlayer 分发,每个 binding 的 hook 只 fire 一次
-- 自己那边,不需要显式 actor filter。
on_round_end_post_summon(function(ctx)
  if 岩脊_rounds:get() <= 0 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 1, { source = Source.Summon })
end)

on_round_end_decay(function(ctx)
  if 岩脊_rounds:get() > 0 then
    岩脊_rounds:sub(1)
    if 岩脊_rounds:get() <= 0 then
      玉璋护盾:add(1)
    end
  end
end)

on_shield_absorb(function(ctx)
  if ctx.target_player ~= my_player or ctx.target_char ~= my_char then return end
  local shield = 玉璋护盾:get()
  if shield <= 0 then return end

  local absorb = min(shield, ctx.value)
  玉璋护盾:sub(absorb)
  ctx.value = ctx.value - absorb
end)
