-- 元素反应系统示例
-- 这个脚本展示了如何用 mod + counter 实现元素反应

-- 目标身上的元素附着计数器（阵营级共享，因为敌人可能在不同角色间切换）
-- 实际游戏中，元素附着是在敌方角色上的

-- 注册元素反应处理器
if not reaction_mod_attached then
    function mod_elemental_reaction()
        -- 注意：这里简化处理，实际需要访问 damage info
        -- 当前架构下，需要在伤害计算 mod 中检查
        
        -- 伪代码示例：
        -- 1. 获取当前伤害信息（需要 core 支持传递 damage info 到 mod）
        -- 2. 检查伤害元素和目标当前附着
        -- 3. 如果发生反应，修改伤害值并清除/修改附着
        
        -- 例如：火伤害打在水附着上 -> 蒸发，伤害*2
        --       水伤害打在火附着上 -> 蒸发，伤害*2
        --       火伤害打在冰附着上 -> 融化，伤害*2
        --       冰伤害打在火附着上 -> 融化，伤害*1.5
    end
    -- attach_mod("damage_calc", "mod_elemental_reaction")
    reaction_mod_attached = true
end

-- 实际上，我们需要让 core 支持在 damage API 中传递更多信息
-- 或者创建一个 apply_element_damage(target, amount, element) 函数
