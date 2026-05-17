-- characters/坎蒂丝/坎蒂丝.lua
-- source: data/cleaned/character/6804_坎蒂丝.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=6804 parent_class=character element=水 weapon=长柄武器 hp=11 energy=2
--   skills (3 个主动):
--     [0] 流耀枪术·守势 (普通攻击) cost={水:1, 无色:2}  造 2 物理
--     [1] 圣仪·苍鹭庇卫 (元素战技) cost={水:3}          附"苍鹭护盾"+准备"苍鹭震击"
--     [2] 圣仪·灰鸰衒潮 (元素爆发) cost={水:3} 能量:2   造 2 水 + 生成"赤冕祝祷"
-- deferred:
--   - 苍鹭护盾 status + 苍鹭震击 prepare_skill (ADR-0012)
--   - 赤冕祝祷 出战状态 (普攻+1 + 物理转水 + 切换造 1 水)
--   - talent "贯虹的渊嗽"

declare_char("坎蒂丝", { element = Element.Water, weapon = Weapon.Polearm })

declare_counter("hp",     Scope.Self, 11, { max = 11, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
