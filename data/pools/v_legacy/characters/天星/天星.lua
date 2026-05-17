-- characters/天星/天星.lua
declare_char("天星", { element = Element.Geo, weapon = Weapon.Polearm })

declare_counter("hp",     Scope.Self, 13, { max = 13, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 3,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
