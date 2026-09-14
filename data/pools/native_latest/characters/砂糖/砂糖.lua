-- 最新源资料：artifacts/official_latest_20260913/raw/character/；普通七圣召唤规则。
declare_char("砂糖", { element = Element.Anemo, weapon = Weapon.Catalyst })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })

local talent = declare_counter("混元熵增论_装备", Scope.Self, 0, { min = 0, max = 1 })
register_buff(talent, { remove_on_death = true })
