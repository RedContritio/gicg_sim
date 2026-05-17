-- Element Fire. Variant of 测试角色A with a pure-3-fire skill costing
-- 3 fire for 3 damage (used by the "神秘水流 + tune" scenario where a
-- char with no Any-part in its skill cost makes tune's trade-off
-- visible — tune burns a card but enables the 3F skill to fire).
declare_char("测试角色C", { element = Element.Fire, weapon = Weapon.None })

declare_counter("hp",     Scope.Self, 10, { max = 10, display = "生命" })
declare_counter("energy", Scope.Self, 0,  { max = 2,  display = "能量" })
declare_counter("alive",  Scope.Self, 0,  { max = 1,  display = "存活" })
declare_counter("active", Scope.Self, 0,  { max = 1,  display = "出战" })
