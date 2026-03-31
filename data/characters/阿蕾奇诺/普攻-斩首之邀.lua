-- 阿蕾奇诺普攻 - 斩首之邀
-- 使用 CHARACTER scope 让 E 技能和普攻共享血偿勒令状态

-- 创建或获取血偿勒令计数器（角色级共享，已存在则自动返回同一个）
blood_debt = create_counter("blood_debt", 0, SCOPE_CHARACTER)

function on_normal_attack()
    local bonus = get_counter(blood_debt)
    local total_damage = 2 + bonus
    damage(total_damage, PHYSICAL)
    if bonus > 0 then
        set_counter(blood_debt, 0)
    end
end
