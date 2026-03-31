-- 香菱元素战技 - 锅巴出击（召唤物示例）
-- 召唤锅巴，造成火伤害，锅巴持续2回合，每回合末喷火

-- 创建或获取锅巴的计数器
guoba_duration = create_counter("guoba_duration", 0, SCOPE_CHARACTER)

-- 注册锅巴的回合末触发（如果还没注册）
if not guoba_mod_attached then
    function mod_guoba_trigger()
        -- 检查锅巴是否还存在
        if get_counter(guoba_duration) <= 0 then return end
        
        -- 锅巴喷火！
        damage(1, PYRO)
        
        -- 减少持续时间
        modify_counter(guoba_duration, -1)
    end
    attach_mod("end_phase", "mod_guoba_trigger")
    guoba_mod_attached = true
end

function on_elemental_skill()
    -- 香菱召唤锅巴，造成初始伤害
    damage(1, PYRO)
    
    -- 设置锅巴持续2回合
    set_counter(guoba_duration, 2)
end
