# 设计决策日志

## 第一阶段：DSL API 调整

### D1：get_next_char 保留原名，增加 Player 常量支持

**问题：** `get_next_char(player, char)` 应当接受 Player 常量。

**方案：**
- A) 合并为通用的 `get_char(target)` 查询——过于复杂，`get_char(name)` 已存在
- B) 保留 `get_next_char`，包装为接受 Player 常量——改动最小，命名清晰

**决策：** B。`get_next_char` 语义明确（"从指定位置起的下一个存活角色"）。仿照 `get_active_char` 添加 `_resolve_p` 包装。用法：`get_next_char(Player.Own, ctx.actor_char)`。

### D2：draw_card_self → draw_card(player, count)

**问题：** `draw_card_self(n)` 只能为当前上下文玩家摸牌，无法为对手摸牌。

**决策：** 替换为 `draw_card(player, count)` Lua 包装，接受 Player 常量。移除 `draw_card_self`。

### D3：force_switch_next → force_switch

**问题：** 函数名过于冗长。"next" 是隐含的（始终切换到下一个存活角色）。

**决策：** 重命名为 `force_switch(player)`。已通过包装支持 Player 常量。

### D4：死代码清理

**决策：** 从 char.lua 中移除 `register_on_all_hp`、`register_on_all_energy`（data/ 中无任何消费者）。从 bridge.go 注册中移除 `count_alive`。Go 函数保留，供潜在的测试使用。

---

继续阅读（按主题分册）：
- `../../2_decisions/adr-0002-capi_obs_d5_d9.md` — Stage 3: C API & 观测空间 (D5-D9)
- `../../2_decisions/adr-0003-engine_bugs_d10_d13.md` — Stage A 引擎 bug 修复 (D10-D13)
- `../eras/ppo_pre_az/decisions/training_design.md` — Stage A 训练
  管线设计 (D14-D20) **(已归档)**。PPO pre-AZ 时代决策,配合 AZ 迁移于
  2026-04-15 连同 PPO 训练栈一起归档。当前训练决策去 `../../2_decisions/adr-0005-az_decisions_d1_d14.md`。

> 2026-04-26 docs 大改: 本文从 `docs/decisions/README.md` 移到当前路径,
> 作为 D1-D4 (DSL API) 的档案保留。新 ADR 走 `../../2_decisions/adr-NNNN-*.md` 编号。
