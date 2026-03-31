-- 阿蕾奇诺普攻 - 斩首之邀
-- 使用角色级共享计数器，让E技能和普攻共享血偿勒令状态

-- 创建或获取血偿勒令计数器（角色级共享，已存在则自动返回同一个）
blood_debt = create_counter("blood_debt", 0, 5, SCOPE_CHAR_SHARED)

function on_normal_attack()
    local bonus = blood_debt:get()
    local total_damage = 2 + bonus
    damage(ACTIVE_ENEMY, total_damage, PHYSICAL)
    if bonus > 0 then
        blood_debt:clear()
    end
end
