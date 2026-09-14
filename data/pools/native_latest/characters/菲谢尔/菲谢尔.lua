-- 最新官方快照普通角色，技能与关联效果见同目录。
declare_char("菲谢尔", { element = Element.Electro, weapon = Weapon.Bow })
declare_counter("hp", Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0, { max = 3, display = "能量" })
declare_counter("alive", Scope.Self, 0, { max = 1, display = "存活" })
declare_counter("active", Scope.Self, 0, { max = 1, display = "出战" })

local talent = declare_counter("噬星魔鸦_装备", Scope.Self, 0, { min = 0, max = 1 })
register_buff(talent, { remove_on_death = true })
