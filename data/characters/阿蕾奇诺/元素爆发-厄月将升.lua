-- 阿蕾奇诺元素爆发 - 厄月将升
-- 使用角色级共享计数器

-- 创建或获取生命之契计数器（角色级共享，已存在则自动返回同一个）
life_debt = create_counter("life_debt", 0, 5, SCOPE_CHAR_SHARED)

function on_elemental_burst()
    damage(ACTIVE_ENEMY, 4, PYRO)
    local debt = life_debt:get()
    if debt > 0 then
        life_debt:clear()
    end
end
