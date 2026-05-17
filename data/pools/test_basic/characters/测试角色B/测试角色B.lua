-- Element Electro. Sister of 测试角色A; the test scenario keeps B in
-- the backline with a cross-element (fire) skill cost so greedy sees
-- a high-value action it cannot reach without burning resources that
-- make other actions unaffordable.
declare_char("测试角色B", { element = Element.Electro, weapon = Weapon.None })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
