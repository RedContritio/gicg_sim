-- characters/玛薇卡/玛薇卡.lua
-- source: data/cleaned/character/505479_玛薇卡.yaml
-- 字段对照 (强制锁定 — spike test 断言):
--   id=505479 parent_class=character element=火 weapon=双手剑 hp=10 energy=3
--   skills (3 个主动 + 1 被动 + 3 召唤物特技):
--     [0] 以火织命   (普通攻击) cost={火:1, 无色:2} 造 2 物理
--     [1] 称名之刻   (元素战技) cost={火:3}        造 1 火 + 战意+1 + 生成 3 张驰轮车手牌
--     [2] 燔天之时   (元素爆发) cost={火:4} 能量:3 造 4 火 (若消耗 6 战意 +附"死生之炉")
--     [3] 战意 (被动): 不获充能,消耗夜魂/普攻后 +1 战意; 战技/爆发时附"诸火武装·焚曜之环"
--     召唤物特技: 驰轮车·跃升 / ·涉渡 / ·疾驰 (玛薇卡专属手牌, 战斗行动)
-- deferred (本 lua 未实现):
--   - 战意 被动 (能量重定义为"战意" 计数器,不获 充能)
--   - "诸火武装·焚曜之环" 出战状态 (其他角色普攻/特技后,消耗 1 夜魂 → 1 火)
--   - "死生之炉" 出战状态 (普攻+1, 不消夜魂)
--   - 驰轮车 3 个特技 (称名之刻 生成 3 张,实际是手牌 specialty + prepare_skill)
--   - talent "燔天的祝禧"

declare_char("玛薇卡", { element = Element.Fire, weapon = Weapon.Claymore })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 3,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
