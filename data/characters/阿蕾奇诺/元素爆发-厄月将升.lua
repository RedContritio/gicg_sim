-- 阿蕾奇诺元素爆发 - 厄月将升
-- 使用 CHARACTER scope 让技能和普攻共享状态

-- 创建或获取生命之契计数器（角色级共享，已存在则自动返回同一个）
life_debt = create_counter("life_debt", 0, SCOPE_CHARACTER)

function on_elemental_burst()
    damage(4, PYRO)
    local debt = get_counter(life_debt)
    if debt > 0 then
        set_counter(life_debt, 0)
    end
end
