-- characters/柯莱/柯莱.lua
-- source: data/cleaned/character/5357_柯莱.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=5357 parent_class=character element=草 weapon=弓 hp=11 energy=2
--   skills (3 个主动):
--     [0] 祈颂射艺   (普通攻击) cost={草:1, 无色:2} 造 2 物理
--     [1] 拂花偈叶   (元素战技) cost={草:3}        造 3 草
--     [2] 猫猫秘宝   (元素爆发) cost={草:3} 能量:2 造 2 草 + 召唤"柯里安巴"
-- deferred:
--   - "柯里安巴" 召唤物 (结束阶段 2 草, 可用次数 2)
--   - talent "飞叶迴斜"

declare_char("柯莱", { element = Element.Dendro, weapon = Weapon.Bow })

declare_counter("hp",     Scope.Self, 11, { max = 11, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
