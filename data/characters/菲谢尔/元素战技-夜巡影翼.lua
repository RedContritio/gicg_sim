-- 菲谢尔元素战技 - 夜巡影翼（召唤奥兹）

-- 创建或获取奥兹使用次数计数器（技能级特有）
if oz_uses == nil then
    oz_uses = create_counter("oz_uses", 0, 2)
end

-- 注册奥兹触发 mod（如果还没注册）
if not oz_mod_attached then
    function mod_oz_trigger()
        if oz_uses:get() <= 0 then return end
        damage(ACTIVE_ENEMY, 1, ELECTRO)
        oz_uses:dec(1)
    end
    attach_mod("end_phase", "mod_oz_trigger")
    oz_mod_attached = true
end

function on_elemental_skill()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
