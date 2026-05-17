-- Stage 0 training char: Fire element, 10 HP, 3 physical-damage skills
-- tuned for the minimum-viable RL pipeline test per
-- docs/3_plans/curriculum/plan.md Stage 0. No buffs, no reactions
-- (skills deal Physical so they bypass the engine's reaction pipeline
-- even when the scenario puts both sides on fire — mirror 1v1 is
-- still reaction-free by construction).
declare_char("测试角色D", { element = Element.Fire, weapon = Weapon.None })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
