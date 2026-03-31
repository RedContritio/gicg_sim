-- 迪卢克元素战技 - 逆焰之刃
-- 逻辑：第1、2段伤害3，第3段伤害5，然后重置

-- 创建或获取段数计数器（技能级特有）
if e_combo == nil then
    e_combo = create_counter("e_combo", 0, 3)
end

function on_elemental_skill()
    local combo = e_combo:get()
    
    -- 第3段（combo == 2）伤害为5，其他为3
    if combo == 2 then
        damage(ACTIVE_ENEMY, 5, PYRO)
        -- 重置计数器
        e_combo:clear()
    else
        damage(ACTIVE_ENEMY, 3, PYRO)
        -- 增加计数
        e_combo:inc(1)
    end
end
