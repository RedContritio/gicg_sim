-- 阿蕾奇诺元素战技 - 万相化灰
-- 使用角色级共享计数器

-- 创建或获取血偿勒令计数器（角色级共享，已存在则自动返回同一个）
blood_debt = create_counter("blood_debt", 0, 5, SCOPE_CHAR_SHARED)

function on_elemental_skill()
    damage(ACTIVE_ENEMY, 2, PYRO)
    blood_debt:set(3)
end
