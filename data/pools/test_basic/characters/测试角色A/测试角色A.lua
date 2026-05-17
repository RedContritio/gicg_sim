-- Element Fire. Used only by tools/test_dice_scheduling.py to probe
-- greedy-vs-optimal dice payment scheduling. Minimal counters + one
-- physical-damage skill, no reactions / buffs / equipment hooks.
declare_char("测试角色A", { element = Element.Fire, weapon = Weapon.None })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
