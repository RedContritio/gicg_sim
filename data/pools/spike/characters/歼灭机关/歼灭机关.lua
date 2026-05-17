-- 歼灭机关 spike(简化版,验证 prepare-skill 机制)
-- 完整效果见 data/cleaned/monster/501447_歼灭特化型机关.yaml
-- spike 只保留:HP / 普通攻击 / 元素战技(高频旋击)/ 元素爆发占位
-- 关键:元素战技 set_preparing → 下次该方 turn 自动 silent invoke 超速旋击

declare_char("歼灭机关", { element = Element.Fire, weapon = Weapon.Other })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
