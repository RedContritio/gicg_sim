-- 甘雨元素战技 - 山泽麟迹（冰莲）

-- 创建或获取冰莲使用次数计数器（技能级特有）
ice_lotus = create_counter("ice_lotus", 0, SCOPE_SKILL)

-- 注册冰莲触发 mod（如果还没注册）
if not lotus_mod_attached then
    function mod_icelotus_trigger()
        if get_counter(ice_lotus) <= 0 then return end
        damage(1, CRYO)
        modify_counter(ice_lotus, -1)
    end
    attach_mod("end_phase", "mod_icelotus_trigger")
    lotus_mod_attached = true
end

function on_elemental_skill()
    damage(1, CRYO)
    set_counter(ice_lotus, 2)
end
