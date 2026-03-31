-- 菲谢尔元素战技 - 夜巡影翼（召唤奥兹）

-- 创建或获取奥兹使用次数计数器（技能级特有）
oz_uses = create_counter("oz_uses", 0, SCOPE_SKILL)

-- 注册奥兹触发 mod（如果还没注册）
if not oz_mod_attached then
    function mod_oz_trigger()
        if get_counter(oz_uses) <= 0 then return end
        damage(1, ELECTRO)
        modify_counter(oz_uses, -1)
    end
    attach_mod("end_phase", "mod_oz_trigger")
    oz_mod_attached = true
end

function on_elemental_skill()
    damage(1, ELECTRO)
    set_counter(oz_uses, 2)
end
