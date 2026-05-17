-- characters/猫咪/猫咪.lua
declare_char("猫咪", { element = Element.Ice, weapon = Weapon.Bow })

declare_counter("hp",     Scope.Self, 15, { max = 15, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 3,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
