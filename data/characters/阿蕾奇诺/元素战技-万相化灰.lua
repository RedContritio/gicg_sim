-- 阿蕾奇诺元素战技 - 万相化灰
-- 使用 CHARACTER scope 让 E 技能和普攻共享血偿勒令状态

-- 创建或获取血偿勒令计数器（角色级共享，已存在则自动返回同一个）
blood_debt = create_counter("blood_debt", 0, SCOPE_CHARACTER)

function on_elemental_skill()
    damage(2, PYRO)
    set_counter(blood_debt, 3)
end
