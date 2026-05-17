-- ADR-0019 §A.3 Phase 1 — Arkhe (始基力) 基础设施。
--
-- 始基反应(荒/芒湮灭)= 枫丹版本引入的反应种类,触发条件:
--   "具有「能源特征:荒性」或「能源特征:芒性」的「发条机关」在受到具有
--    相反性质「始基力」的伤害后,会发生荒芒湮灭效应,并转换为「失能形态」"
--
-- buff-owned 路线:不入 system/reactions/(那是 pool-agnostic 全局反应,
-- 任何卡都可触发);始基反应仅涉及枫丹特定角色 / 机关,作 buff-owned hook
-- 写在 character 文件,共享基础设施(本 lib + Arkhe enum 在 engine 注册)。
--
-- Arkhe enum 在 engine builtins_enums.go 注册(Arkhe.None / Pneuma / Ousia)。
--
-- 协议(strict §B.5 hook 时机):
--   1. attacker 角色 lua 内,用 _arche_marker counter (priority=100 抢早 set):
--        local arche = get_counter("_arche_marker", Scope.Global)
--        on_damage_type(100, function(ctx)
--          if ctx.actor_player == my_player and ctx.actor_char == my_char then
--            arche:set(Arkhe.Ousia)  -- 或 Arkhe.Pneuma,看自己始基力身份
--          end
--        end)
--        on_after_damage(-100, function(ctx)
--          if ctx.actor_player == my_player and ctx.actor_char == my_char then
--            arche:set(Arkhe.None)  -- 出口 reset (低优先级最后跑)
--          end
--        end)
--
--   2. 机关类(target)的 entity 内,after_damage hook 监听:
--        local arche = get_counter("_arche_marker", Scope.Global)
--        on_after_damage(function(ctx)
--          if ctx.target_player == my_player and ctx.target_char == my_char then
--            local actor_arkhe = arche:get()
--            -- 检查 vs 自身能源特征 (例 self.energy_signature == Arkhe.Pneuma
--            -- 时 actor_arkhe == Arkhe.Ousia 触发湮灭 — 相反始基)
--            if 是相反始基力 then
--              -- 触发湮灭: 转换失能形态
--            end
--          end
--        end)
--
-- 嵌套 damage call(扩散 / 反应子伤害)在同一 actor 上覆盖同值,无问题;
-- 跨 actor 嵌套(罕见 corner case)目前不支持栈式管理,作 known limitation。

local _arche_marker = declare_counter("_arche_marker", Scope.Global, 0, {
    min = 0,
    max = 2,
    display = "始基标记",
})
