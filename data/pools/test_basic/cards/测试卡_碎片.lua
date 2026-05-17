-- 消耗 1 任意骰,直接对敌方当前出战造成 1 物理伤害。source 继承自
-- on_card_play 事件帧 = SrcCard (所以不会触发 "下次技能 ×2" buff 的
-- 条件,那个 buff 只对 SrcSkill 伤害生效)。
local ref = declare_card("测试卡_碎片", { dices = { any = 1 } })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  deal_damage(Target.EnemyActive, Element.Physical, 1)
end)
