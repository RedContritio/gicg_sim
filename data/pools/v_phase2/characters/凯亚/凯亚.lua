-- characters/凯亚/凯亚.lua
-- source: data/cleaned/character/5375_凯亚.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=5375 parent_class=character element=冰 weapon=单手剑 hp=10 energy=2
--   skills (3 个主动):
--     [0] 仪典剑术 (普通攻击) cost={冰:1, 无色:2} 造 2 物理
--     [1] 霜袭     (元素战技) cost={冰:3}        造 3 冰
--     [2] 凛冽轮舞 (元素爆发) cost={冰:4} 能量:2 造 1 冰 + 生成"寒冰之棱"
-- deferred (本 lua 未实现,后续补):
--   - 凛冽轮舞 "寒冰之棱" 召唤物/状态 (ref kaeya.ts: 切换角色后造 2 冰伤,可用次数 3)
--   - talent "冷血之剑" (装备牌) — 本 pool 暂不录天赋牌

declare_char("凯亚", { element = Element.Ice, weapon = Weapon.Sword })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
