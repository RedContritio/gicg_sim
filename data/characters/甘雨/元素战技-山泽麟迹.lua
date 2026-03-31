-- 甘雨元素战技 - 山泽麟迹（冰莲）

-- 创建或获取冰莲使用次数计数器（技能级特有）
if ice_lotus == nil then
    ice_lotus = create_counter("ice_lotus", 0, 2)
end

-- 注册冰莲触发 mod（如果还没注册）
if not lotus_mod_attached then
    function mod_icelotus_trigger()
        if ice_lotus:get() <= 0 then return end
        damage(ACTIVE_ENEMY, 1, CRYO)
        ice_lotus:dec(1)
    end
    attach_mod("end_phase", "mod_icelotus_trigger")
    lotus_mod_attached = true
end

function on_elemental_skill()
    damage(ACTIVE_ENEMY, 1, CRYO)
    ice_lotus:set(2)
end
