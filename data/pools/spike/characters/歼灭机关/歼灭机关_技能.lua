-- 歼灭机关 技能 spike — 验证 prepare-skill 机制
-- 完整 raw 见 data/cleaned/monster/501447_歼灭特化型机关.yaml
-- 简化:普通攻击 / 高频旋击(prepare 触发 超速旋击)/ 占位爆发

local 歼灭机关 = get_char("歼灭机关")
local my_player = 歼灭机关:owner_player()
local my_char = 歼灭机关:owner_char()

-- 普通攻击:1 物理(简化:1 火,因 spike 不实现物理→火 改造)
local 普攻 = declare_skill(歼灭机关, "普通攻击", 3)
on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 普攻 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Skill })
end)

-- 元素爆发占位(spike 不重要,但 declare 必须)
local 爆发 = declare_skill(歼灭机关, "爆发占位", 3, 2)
on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 爆发 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 3, { source = Source.Skill })
end)

-- 超速旋击:仅作为 preparing 的目标,不能直接选(spike 不强制 — DSL
-- 通过不在 declare_skill 加 normal-attack 标志即可。完整 enginee
-- 应让"准备目标 skill"对玩家不可选,但 spike 阶段能 declare 即可)。
local 超速旋击 = declare_skill(歼灭机关, "超速旋击", 3)
on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 超速旋击 then return end
  -- "造成 1 物理(spike 用火)+ 此角色额外获得 1 充能"
  deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Skill })
  -- 额外充能(在 silent invoke 时 engine canonical 不增加,DSL 自己处理)
  local energy_counter = get_counter("energy", Scope.Self)
  energy_counter:add(1)
end)

-- 高频旋击:set_preparing → 下次该方 turn engine 自动 silent invoke 超速旋击
local 高频旋击 = declare_skill(歼灭机关, "高频旋击", 3, 0)
on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 高频旋击 then return end
  -- "造成 1 物理 + 准备技能:超速旋击"
  deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Skill })
  -- 用 ctx.actor_player(实际 0/1)而非 my_player(可能是 lazy proxy)
  set_preparing(ctx.actor_player, 超速旋击)
end)
