-- 系统级元素反应mod
-- 注册到 damage_calc 事件，自动处理所有元素反应

function elemental_reaction_handler()
    -- 获取当前伤害信息
    local dmg = get_current_damage()
    if not dmg then return end
    
    -- 物理伤害不参与反应
    if dmg.element == PHYSICAL or dmg.element == PIERCING then
        return
    end
    
    local target = dmg.target
    local amount = dmg.amount
    local element = dmg.element
    local final_amount = amount
    
    -- 检查目标是否有元素附着
    -- 蒸发：火+水 或 水+火，伤害*2
    if element == PYRO and has_aura_on_char(target, HYDRO) then
        final_amount = amount * 2
        remove_aura_from_char(target, HYDRO)
        print("💧🔥 蒸发！伤害 " .. amount .. " -> " .. final_amount)
    elseif element == HYDRO and has_aura_on_char(target, PYRO) then
        final_amount = amount * 2
        remove_aura_from_char(target, PYRO)
        print("🔥💧 蒸发！伤害 " .. amount .. " -> " .. final_amount)
    end
    
    -- 融化：火+冰（2倍），冰+火（1.5倍）
    if element == PYRO and has_aura_on_char(target, CRYO) then
        final_amount = amount * 2
        remove_aura_from_char(target, CRYO)
        print("❄️🔥 融化！伤害 " .. amount .. " -> " .. final_amount)
    elseif element == CRYO and has_aura_on_char(target, PYRO) then
        final_amount = amount * 3 / 2
        remove_aura_from_char(target, PYRO)
        print("🔥❄️ 融化！伤害 " .. amount .. " -> " .. final_amount)
    end
    
    -- 超导：冰+雷，伤害+1
    if (element == CRYO and has_aura_on_char(target, ELECTRO)) or
       (element == ELECTRO and has_aura_on_char(target, CRYO)) then
        final_amount = amount + 1
        if element == CRYO then
            remove_aura_from_char(target, ELECTRO)
        else
            remove_aura_from_char(target, CRYO)
        end
        print("⚡❄️ 超导！伤害 " .. amount .. " -> " .. final_amount)
    end
    
    -- 超载：火+雷，伤害+2
    if (element == PYRO and has_aura_on_char(target, ELECTRO)) or
       (element == ELECTRO and has_aura_on_char(target, PYRO)) then
        final_amount = amount + 2
        if element == PYRO then
            remove_aura_from_char(target, ELECTRO)
        else
            remove_aura_from_char(target, PYRO)
        end
        print("⚡🔥 超载！伤害 " .. amount .. " -> " .. final_amount)
    end
    
    -- 感电：水+雷，伤害+1
    if (element == HYDRO and has_aura_on_char(target, ELECTRO)) or
       (element == ELECTRO and has_aura_on_char(target, HYDRO)) then
        final_amount = amount + 1
        if element == HYDRO then
            remove_aura_from_char(target, ELECTRO)
        else
            remove_aura_from_char(target, HYDRO)
        end
        print("⚡💧 感电！伤害 " .. amount .. " -> " .. final_amount)
    end
    
    -- 冻结：水+冰
    if (element == HYDRO and has_aura_on_char(target, CRYO)) or
       (element == CRYO and has_aura_on_char(target, HYDRO)) then
        remove_aura_from_char(target, HYDRO)
        remove_aura_from_char(target, CRYO)
        apply_aura_to_char(target, CRYO, 1) -- 冻元素持续1回合
        print("❄️💧 冻结！")
    end
    
    -- 如果没有发生反应，给目标添加元素附着
    if final_amount == amount then
        apply_aura_to_char(target, element, 2)
    end
    
    -- 更新伤害值
    set_damage_amount(final_amount)
end

-- 注册系统级mod
attach_mod("on_damage_calc", "elemental_reaction_handler")
