-- characters/克洛琳德/克洛琳德.lua
-- source: data/cleaned/character/503960_克洛琳德.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=503960 parent_class=character element=雷 weapon=单手剑 hp=10 energy=2
--   skills (3 个主动):
--     [0] 逐影之誓 (普通攻击) cost={雷:1, 无色:2} 造 1 物理 (附"夜巡"时改 1 雷 + 普攻 +2 契)
--     [1] 狩夜之巡 (元素战技) cost={雷:2}        附"夜巡" + 移除"生命之契" → 按数造雷伤+治疗 (≤4)
--     [2] 残光将终 (元素爆发) cost={雷:3} 能量:2 造 3 雷 + 自附 4 层"生命之契"
--   始基力: 荒性 (Arkhe.Ousia)
-- deferred (本 lua 未实现):
--   - "夜巡" 出战状态 (持续 1 回合 + 治疗→契 转换 + 普攻物理→雷 + 自附 2 契)
--   - "生命之契" 出战状态 (治疗抵消 + 可叠加)
--   - 始基力 Ousia hook (Pneuma 攻击触发 + on_damage_type 标记)
--   - talent "破夜的明焰"

declare_char("克洛琳德", { element = Element.Electro, weapon = Weapon.Sword })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
