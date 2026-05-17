-- characters/凝光/凝光.lua
-- source: data/cleaned/character/5359_凝光.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=5359 parent_class=character element=岩 weapon=法器 hp=10 energy=3
--   skills (3 个主动):
--     [0] 千金掷    (普通攻击) cost={岩:1, 无色:2} 造 1 岩
--     [1] 璇玑屏    (元素战技) cost={岩:3}        造 2 岩 + 生成"璇玑屏"
--     [2] 天权崩玉  (元素爆发) cost={岩:3} 能量:3 造 6 岩 (璇玑屏在场 +2)
-- deferred:
--   - 璇玑屏 出战状态 (我方出战角色受到≥2伤害时,抵消 1, 可用次数 2)
--   - 天权崩玉 +2 buff 条件 (璇玑屏在场)
--   - talent "储之千日,用之一刻"

declare_char("凝光", { element = Element.Geo, weapon = Weapon.Catalyst })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 3,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
