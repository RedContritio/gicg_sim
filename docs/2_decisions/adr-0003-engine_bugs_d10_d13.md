# 设计决策 — Stage A：引擎 Bug 修复

> **MOVED to `openspec/changes/archive/0003-engine-bugs-d10-d13/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0003-engine-bugs-d10-d13/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0003-engine-bugs-d10-d13/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


> 本文是早期 D1-D4 (DSL API 调整) + D5-D9 (capi/obs) 的延续,前置阅读
> `../5_history/decisions_legacy/dsl_api_d1_d4.md` 与 `adr-0002-capi_obs_d5_d9.md`。
> 本文记录 mirror match 训练阻塞期间发现并修复的引擎 bug (D10-D13)。

## Stage A：镜像对战 Bug 修复与训练管线优化

### D10：回合翻转跳过了已宣告结束的对手（Bug 修复）

**问题：** 随机 vs 随机的 1v1 镜像对战中，P1 胜率高达 99%（赤蝶 47/50，墨客/猫咪/刻师傅/天星 50/50）。这阻塞了 phase0a 的 vs-random 训练——由于结构性回合顺序偏差主导了一切，智能体的胜率始终无法达到 60% 的晋级门槛。

**排查：** 对动作计数进行插桩：P0 每局调用 EndTurn 平均 13.77 次，P1 仅 7.93 次。双方均使用均匀随机动作选择，理论上不应有不对称性。

**根本原因：** `gicg_engine/action.go` 中 BattleAction 的回合翻转是无条件的：
```go
if flipCtx.BattleAction {
    g.Turn = 1 - g.Turn
}
```
P0 宣告结束后，P1 执行 BattleAction → 回合翻回 P0 → P0 被轮询但只能选择 EndTurn（已宣告结束）→ 回合再翻回 P1 → 循环。P1 每次 BattleAction 都会消耗 P0 一次无效的 EndTurn，不断消耗 P0 的有效行动配额，而 P1 持续造成伤害。

**决策：** 添加 `(g *Game) flipTurn()` 辅助函数，检查 `g.Players[next].DeclaredEnd`。若下一位玩家已宣告结束，当前玩家保持独占控制权，直到其也宣告结束——与原神 TCG 规则一致。

```go
func (g *Game) flipTurn() {
    next := 1 - g.Turn
    if !g.Players[next].DeclaredEnd {
        g.Turn = next
    }
}
```

三处回合翻转位置（`executeSkill`、`executeCard`、`executeSwitch`）均改为调用 `flipTurn()`，而非内联 `g.Turn = 1 - g.Turn`。

**回归测试：** `gicg_engine/tests/turn_flip_test.go` — 验证 P0 EndTurn 后 P1 使用技能，回合保持在 P1。

**为何一直被掩盖：** 所有对任意智能体的 1v1 镜像对战评估都受到同样的偏差影响，因此训练出的智能体看起来同样羸弱（vs random 约 50% 胜率）。训练智能体的评估胜率与随机策略相同，掩盖了引擎本身存在 bug 的事实。

### D11：镜像对战中 per-name CharEntry 别名问题（Bug 修复）

**问题：** 两次加载 `赤蝶.lua`（每个玩家绑定一次）导致 P0 的角色**零技能**（`BySlot[0][0].SkillIDs == []`），而 P1 拥有全部三个技能。镜像对战在 DSL→引擎绑定层就已从根本上损坏。

**根本原因：** 三个独立设计决策相互作用产生了不良后果：

1. `declare_char(name, opts)` 总是创建新的 `*CharEntry` 并覆写 `rt.Chars.ByName[name]`。两次加载角色文件后，第一个条目变成孤立对象（仍被 `BySlot[0][0]` 引用，但从 `ByName` 中消失）。
2. 技能文件（`赤蝶_枪.lua` 等）通过 `LoadFilesWithDeps` 全局加载一次，通过 `get_char("赤蝶") → ByName[赤蝶]` 解析角色代理，而此时 `ByName` 只指向 P1 的条目。
3. `declare_skill` 将技能 ID 注册到 `charProxy.Entry`（= P1 的条目），调用 `g.AddSkill(charEntry.PlayerIdx, charEntry.CharIdx, skillID)` 时只执行一次。P0 的条目从未接收到任何技能 ID。

**下游症状：**
- P0 的 `GetLegalActions()` 只返回 `[]Action{ActionEndTurn}`（第 47-48 行："异常状态"分支从未触发，但技能确实为空）。
- Replay 格式崩溃，输出 `赤蝶: { , 状态: {…} }`（孤立逗号），因为 `buildRoleMap` 遍历 `ByName` 时看到模板条目的 `HPCounterID = -1`。（见 D13。）
- 随机 vs 随机的镜像对战被 D10（回合翻转 bug 同样存在）所掩盖，现有的非镜像测试通过，无人发现。

**决策：** 将 CharEntry 拆分为"模板"（存于 `ByName`，共享）和"per-slot"（存于 `BySlot`，各绑定独有）。**每次绑定时**分别加载角色相关 DSL 文件，而非全局加载一次。

具体实现：

1. `declare_char` 变为**幂等**：若 `ByName[name]` 已存在则直接返回。
2. `bind_char` 将模板克隆为全新的 `CharEntry`（拥有独立的 `PlayerIdx/CharIdx/HPCounterID/EnergyCounterID/AliveCounterID/ActiveCounterID/Skills` 映射），存入 `BySlot[p][c]`。模板不会被 bind_char 修改。
3. `get_char` 在有槽上下文时（per-binding 加载）返回 `BySlot[currentOwnerPlayer][currentOwnerChar]`，否则回退到 `ByName` 模板。
4. `declare_skill` 将技能 ID 注册到**模板**（规范的，跨槽位共享），同时也附加到当前 owner ctx 的槽位条目（调用 `g.AddSkill(pi, ci, skillID)` 和 `registerSkillHooks(slot)`）。
5. `registerSkillHooks` 添加玩家+角色过滤（`if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar { return }`），避免 per-slot 注册跨槽触发。
6. 新加载入口 `LoadCharFilesPerBinding(paths, playerIdx, charIdx)` 使用固定的 owner 上下文运行拓扑排序加载，绕过全局拓扑加载器的自动设置逻辑。卡牌（`data/cards/`）仍通过全局 `LoadFilesWithDeps`。
7. 测试辅助函数（`helpers_test.go`）和 `capi.go` 都有 `splitDSLPaths`，将 `data/characters/<name>/` 的文件与 `data/cards/` 文件分离；角色文件通过 per-binding 加载器处理。

**回归测试：** `gicg_engine/tests/mirror_test.go::TestMirrorMatchSkillsWork` — 验证镜像对战初始化后 `BySlot[0][0].SkillIDs` 和 `BySlot[1][0].SkillIDs` 均已填充。

**为何之前未被发现：** 所有现有 Go 测试都刻意使用**非镜像**角色（赤蝶 vs 墨客，猫咪 vs 刻师傅等）；`TestBasic_AllCharPairs` 中有 `if c0 == c1 { continue }` 跳过所有镜像组合。镜像对战从未在 CI 中被执行过。第一次运行是在 phase0a 的训练配置使用 1v1 随机镜像时。

### D12：引擎 Bug 修复验证（随机基准线）

修复 D10 + D11 后，随机 vs 随机的 1v1 镜像对战结果（每个角色 50 局）：

| 角色 | P0 胜 | P1 胜 |
|------|-------|-------|
| 赤蝶 | 27 | 23 |
| 墨客 | 26 | 24 |
| 猫咪 | 37 | 13 |
| 刻师傅 | 29 | 21 |
| 天星 | 45 | 5 |

赤蝶/墨客/刻师傅 在采样误差范围内。猫咪/天星 仍偏向 P0——这是各角色机制导致的残余先手优势（天星首回合状态强，猫咪的护盾受益于先手），并非回合顺序 bug。可接受为游戏平衡方差，而非 bug。

phase0a 冒烟测试（修复后）：第一次 30 iter 运行在第 10 iter 达到 100% 胜率。相比修复前 500 iter 最好只有 55%。此修复解锁了整个训练管线。

### D13：Replay 角色状态缺少 HP/能量字段（Bug 修复）

**问题：** 镜像对战的 replay 输出孤立逗号格式 `赤蝶: { , 状态: { 存活: 1, 生命: 10, … } }`。

**根本原因：** `gicg_engine/record/roles.go::buildRoleMap` 遍历 `rt.Chars.ByName` 来收集 HP/Energy/Alive/Active 计数器 ID：

```go
for _, entry := range rt.Chars.ByName {
    if entry.HPCounterID >= 0 { m[entry.HPCounterID] = RoleHP }
    ...
}
```

D11 之后，`ByName` 中存放的是 `HPCounterID = -1` 的**模板**条目（per-slot 计数器 ID 只存在于 `BySlot` 条目——模板仅含元数据）。循环没有为角色计数器附加任何角色，`roleMap` 对角色计数器为空。`writeCharState` 的 `ordered` 切片为空，产生 `"{ %s%s }" % ("", ", 状态: {…}")` = `"{ , 状态: {…} }"`。

**决策：** 直接遍历 `BySlot`：
```go
for pi := 0; pi < 2; pi++ {
    for ci := 0; ci < interp.MaxChars; ci++ {
        entry := rt.Chars.BySlot[pi][ci]
        if entry == nil { continue }
        if entry.HPCounterID >= 0 { m[entry.HPCounterID] = RoleHP }
        ...
    }
}
```

**回归测试：** `gicg_engine/tests/record_test.go::TestRecord_MirrorMatchCharState` — 验证赤蝶 vs 赤蝶 的 replay 输出无孤立逗号，且包含 生命/能量/存活 字段。

### D14：非主动角色死亡时排入了无意义的强制切换（Bug 修复）

**问题：** phase0c（使用 `hybrid_prior0` 对手的镜像 NvN 3v3，仅包含填充卡池）在第 4 次 iter 时，训练会话因 `strict_truncation` AssertionError 崩溃：1/16 个 rollout episode"超时"而未完成。将 `max_episode_steps` 从 200 → 600 → 更高均无效，因为这些"超时"的 episode 实际并不长——步数都 < 100。

**排查：** 添加了 `tools/diag_long_episode.py` 来隔离故障。随机 vs 随机跑 32 个 episode，分布正常（最小 54，p99 97，最大 99），没有触达理论上限 **~186 步/episode**（10 轮 × 2 玩家 × 9 最大动作/回合 + ~6 次死亡强制切换）。引擎本身不会产生超长 episode。

改为 `agent_trace` 模式（手动循环，phase0b 检查点，`torch.manual_seed` 保证可复现性）在 seed 2067 / 2071 / 1013 上复现了故障：约每 30 个 episode 中有 1 个在 50-70 步时 `env.done == False`，而不是在 `max_steps` 上限处。VectorizedRollout 的 `_run` 将其归类为截断：

```python
if n_legal == 0:
    # Force the env to "done" via empty action — should be rare;
    # treat as terminated this episode.
    per_slot[slot] = None
```

出错步骤的状态转储：
```
phase                 = 3 (PhaseAction, not GameOver)
winner                = -1
forced_switch_pending = True
active_p1             = 1
```

引擎处于 `PendingAction.Switch` 状态，没有存活的非主动角色可切换，而主动角色仍然存活，游戏客观上尚未结束。触发动作始终是 `Skill:雷暴`（刻师傅的爆发），其 DSL 在一次调用中触发 `deal_damage(EnemyActive, Electro, 3)` + `deal_damage(EnemyNonActive, None, 2, {penetrate=true})`——多目标一扫清。

**根本原因：** `gicg_engine/interp/builtins.go::registerDeathCheck` 对**每一个**角色死亡都排入强制切换，不论死亡角色是否为主动角色：

```go
g.SetAlive(playerIdx, charIdx, false)
...
if g.Phase != engine.PhaseGameOver {
    g.DeferAction(&engine.Action{
        Kind:      engine.ActionSwitch,
        PlayerIdx: playerIdx,
        Forced:    true,
    })
}
```

对于多目标清场（击杀目标玩家的非主动角色，主动角色仍存活），这会排入 `PendingAction.Switch`，尽管主动角色根本不需要切换。当 `GetLegalActions` 调用 `forcedSwitchActions(pi)` 时，函数排除了仍存活的主动角色（跳过 `k == p.ActiveChar`），找不到任何存活的非主动角色 → 空列表 → 引擎在 PhaseAction 中死锁。

**决策：** 将 DeferAction 的触发条件限定为 `ActiveChar == charIdx`：
```go
if g.Phase != engine.PhaseGameOver &&
    g.Players[playerIdx].ActiveChar == charIdx {
    g.DeferAction(&engine.Action{
        Kind:      engine.ActionSwitch,
        PlayerIdx: playerIdx,
        Forced:    true,
    })
}
```

非主动角色死亡现在只会静默减少可切换目标的数量，不排入任何动作；玩家保留当前主动角色，游戏正常继续。主动角色死亡仍像以前一样排入强制切换，`checkWin`（在 `SetAlive` 内部调用）仍然处理"全部 3 个死亡 → GameOver"的情况，不依赖待处理的切换。

**回归测试：** `gicg_engine/tests/non_active_death_test.go`：
- `TestNonActiveDeath_NoForcedSwitch` — 直接通过 HP 写入杀死 P1 的两个非主动角色，断言 `PendingAction == nil` 且 `GetLegalActions()` 非空且包含 `EndTurn`。
- `TestActiveDeath_DoesForceSwitch` — 杀死 P1 的主动角色，断言确实排入了强制切换，且 `GetLegalActions()` 返回两个存活的非主动角色。

**为何隐藏了这么久：** phase0c 之前，所有阶段都是 1v1 或最大 2v2 的 NvN，对手为 `random`，均匀随机动作极少触发爆发同时满足精确前提（主动 HP > 技能伤害且两个非主动 HP ≤ 穿透伤害）。phase0c 的 `hybrid_prior0` 对手按训练策略行动，其 HP 分布和爆发时机恰好以约 3% 的概率触发该场景。随机 vs 随机诊断：0/32 触发；检查点驱动智能体：2-3/100 触发。

**与 `strict_truncation` 的关系：** Review #11 添加了 `assert no truncation` 来捕获 `max_episode_steps` 过低的情况。在此 bug 中，assert 因错误原因触发——episode 并不太长，而是引擎死锁了。assert 仍然发挥了作用（暴露了真实问题），但错误信息"raise max_episode_steps"具有误导性。保留 assert 不变，因为其主要目的（捕获真实的配置错误）仍然正确；死锁路径现已在引擎层关闭。
