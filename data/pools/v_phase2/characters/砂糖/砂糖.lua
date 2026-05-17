-- characters/砂糖/砂糖.lua
-- source: data/cleaned/character/5361_砂糖.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=5361 parent_class=character element=风 weapon=法器 hp=10 energy=2
--   skills (3 个主动):
--     [0] 简式风灵作成              (普通攻击) cost={风:1, 无色:2} 造 1 风
--     [1] 风灵作成·陆参零捌         (元素战技) cost={风:3}        造 3 风 + 强制切换敌人
--     [2] 禁·风灵作成·柒伍同构贰型  (元素爆发) cost={风:3} 能量:2 造 1 风 + 召唤"大型风灵"
-- deferred:
--   - 风灵作成·陆参零捌 强制切换敌人 (force-switch 敌方出战)
--   - "大型风灵" 召唤物 (结束阶段 2 风, 可用次数 3, 扩散反应变更元素类型)
--   - talent "众法之济"

declare_char("砂糖", { element = Element.Anemo, weapon = Weapon.Catalyst })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
