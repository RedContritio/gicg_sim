# IS-MCTS Go 化迁移方案

> **MOVED to `openspec/changes/archive/0004-is-mcts-migration/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0004-is-mcts-migration/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0004-is-mcts-migration/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


> **Status**: L1 (Phase A) + L3 (Phase B) 已 ship (2026-04-19).
> `[mcts] backend = "go"` 通过 TOML 启用整个 Go MCTS 路径。

> 评估将 MCTS rollout 路径从 Python 迁移到 Go 的收益、成本和分层策略。

## 背景

当前 MCTS 实现（`training/mcts.py`，~1090 行）完全在 Python 中，通过 ctypes 调用 Go 引擎执行游戏状态操作。每次 rollout 的调用链：

```
Python MCTS tree
  ├─ env.snapshot()          → ctypes → Go GameSnapshot
  ├─ env.set_player_hand()   → ctypes → Go GameSetPlayerHand  (determinization)
  ├─ env.set_player_deck()   → ctypes → Go GameSetPlayerDeck
  ├─ env.set_player_dice()   → ctypes → Go GameSetPlayerDice
  ├─ [per depth level]:
  │   ├─ env.get_action_identities() → ctypes → Go
  │   ├─ env.get_legal_action_payments() → ctypes → Go
  │   ├─ env._get_obs()      → ctypes → Go GameGetDynamicObs
  │   ├─ env.step()          → ctypes → Go GameStep
  │   └─ (PUCT selection, backup — pure Python)
  ├─ env.restore()           → ctypes → Go GameRestore
  └─ env.snapshot_free()     → ctypes → Go GameSnapshotFree
```

每次 rollout 大约 5-10 次 ctypes 调用（根节点）+ 1-3 次/深度层级。200 rollouts/search × ~8 深度 = ~3200 ctypes round-trips per decision。

## 当前性能瓶颈（实证）

**2026-04-17 实证数据**（`artifacts/202604170508_profile_smoke/`，
n_workers=1, par=1, lambda=0.5, c1 scenario, 4 games 累积 ~800s）：

| 类别 | 占比 | 单次耗时 | 说明 |
|---|---|---|---|
| **eval RPC** | **79.5%** | 21.8 ms/call | inference_server round-trip（主导） |
| **random rollout** | **14.8%** | 5.6 ms/call | rollout 本体（~15 steps/rollout） |
| env_query | 3.3% | 0.29 ms | `legal_ids_from_env` |
| env_step | 1.9% | 0.22 ms | 树下降 env.step |
| determinize | 0.5% | 0.16 ms | — |
| restore | 0.1% | 0.02 ms | — |

**对比纯 UCT 场景**（`tools/mcts_player.py`，无网络）：rollout 占 93.7%。
两者相差 6×——训练时 eval RPC 完全主导，不是 ctypes 或 rollout。

外推到 C1v4 配置（par=4, n_workers=4, server batch_mean≈4）：
server 批量放大会压缩 eval_s 约 3×，eval 占比降到 ~50%，
rollout 占比升到 25-30%。

## 迁移层级

### Level 0（当前状态）：纯 Python MCTS + ctypes

全部 MCTS 逻辑在 Python。Go 仅提供游戏状态原语。

### Level 1：Rollout 快速路径 Go 化

将 `_random_rollout_value`（随机 rollout 到终局）移入 Go。

- 当前：每次 rollout 到终局需要 ~15 步（`n_rollout_steps/n_rollout`），
  每步 1 次 get_legal_actions + 1 次 step = ~30 ctypes 调用，
  单次 rollout 实测 5.6 ms
- Go 化后：单次 ctypes 调用返回终局胜者
- **实证收益**（n_workers=1, par=1 场景，lambda=0.5）：
  - rollout 部分最乐观 50× 加速 → 89s→1.8s → 节省 14.5% 总时间
  - **训练整体加速 1.15-1.17×**
- **外推到 C1v4（par=4, n_workers=4）**：eval 占比降低后 rollout 占比
  升至 25-30% → **训练整体加速 1.25-1.30×**
- **gauntlet 评估场景**（无网络 eval）：rollout 重新主导（~90%+），
  加速 **6-10×** 仍成立

**修正判断**：L1 Go 化对训练主吞吐的收益远低于原纸面估算；
对 gauntlet 评估仍有显著收益。

**接口**：
```go
// capi 新增
//export GameRandomRollout
func GameRandomRollout(gid C.int, seed C.uint64, maxSteps C.int) C.int
// 返回: winner (0/1/2)
// 在当前状态上执行随机 rollout 直到终局，不修改外部可见状态
```

**Python 侧**：`_random_rollout_value(env, max_steps, rng)` 改为单次 ctypes 调用。

**复杂度**：低。Go 侧已有 `Game.Step()` 和 `GetLegalActions()`，只需组装循环。不涉及树结构。

### Level 2：Determinization + 多步 step 批量化

将"snapshot → determinize → step N 次 → restore"序列打包为单次 ctypes 调用：

```go
//export GameMCTSRolloutBatch
func GameMCTSRolloutBatch(gid C.int, req *C.MCTSBatchReq) *C.MCTSBatchResult
// req: snapshot_id, determinization data, action sequence
// result: per-step obs, legal_actions, action_identities, done, winner
```

减少 per-depth ctypes 往返。但需要在 Go 侧缓存中间状态，接口复杂度高。

### Level 3：完整 MCTS 树 Go 化

将 PUCT 选择、虚拟损失、树展开、backup 全部移入 Go。Python 仅发起搜索请求和接收结果。

**收益**：消除所有 Python 树遍历开销和 GC 压力。
**成本**：极高。需要在 Go 中重现 MCTSNode 树、PUCT 公式、virtual loss 簿记、discovery 检测、lambda 混合等全部逻辑。网络 eval 仍需回调 Python（或 Go 侧加载 ONNX）。

### Level 4：Go MCTS + ONNX 推理

Level 3 基础上，在 Go 侧用 ONNX Runtime 做网络推理，完全消除 Python。

**收益**：理论最优吞吐量。
**成本**：需要维护 Go 侧 ONNX 绑定、模型导出管线、特征编码器的 Go 实现。训练仍在 Python/PyTorch，形成双栈。

## 推荐路径（已基于实证修正）

**Level 1 对训练吞吐收益有限，对 gauntlet 收益显著**。建议按场景区分：

- **若瓶颈是 gauntlet 评估时长**：L1 值得立即做（6-10× 加速）
- **若瓶颈是 training throughput**：**先不做 L1**，改而评估以下两条更高 ROI 路径：
  1. **加大 par / n_workers** 让 server batch_mean 从 ~4 提升到 8-16，
     压缩 eval 占比。工程代价最低
  2. **拆解 eval RPC 22ms 里的组成**（pickle / pipe / torch.forward /
     serialize back），针对真正的瓶颈优化。这才是 79.5% 那块蛋糕

**Level 2-4 判断不变**：Level 2 视 profiling 决定；Level 3-4 短期不推荐。

---

## 2026-04-18 更新：team_size=2 改变优先级, 决定上 L3

### 新实证 (C3 team_size=2, 80 局累计 44608s MCTS 时间)

profile 的占比**颠覆性变化**:

| 类别 | team_size=1 (C1v7) | team_size=2 (C3) | 变化 |
|---|---|---|---|
| rollout | 14.8% (5.6 ms) | **53.9% (19.3 ms)** | 3.6× 占比, 3.4× 单次 |
| eval | 79.5% (21.8 ms) | 32.1% (11.5 ms) | RPC batching 压降 |
| descend | <5% | 13.1% (4.7 ms) | 深度变长 |

**原因**: team_size=2 的 n_steps 从 ~25 升到 78 (3.3×), 每次 rollout 要到终局走更多步. rollout 成为主导.

### 重算 Amdahl

| 方案 | team_size=1 | team_size=2 |
|---|---|---|
| L1 (rollout Go) | 1.15-1.30× | **2.1×** |
| L3 (full Go) | ~1.5× | **~2.8×** |

team_size=2 使 L1 从"勉强值" 变"必做", L3 从"不推荐" 变"高 ROI".

### 决策: 分阶段上 L3

用户 2026-04-18 确认: "把 mcts 完全 go 化, 不减少 rollouts 也不做 tree reuse". 保持算法严格性, 换 Go 的原生性能.

**分三阶段**, 每阶段独立验证 + commit:

#### 阶段 A: Level 1 (rollout Go 化) — 1 天

先交付 L1 作 stepping stone. 独立可验证 + smoke 无回归. 是 L3 的组件.

#### 阶段 B: Go MCTS kernel (descend + PUCT) — 2-3 天

把树下降和 PUCT 搬到 Go. 树结构仍在 Python (为了先减小 scope).

#### 阶段 C: Full Go MCTS + Python eval RPC bridge — 2-4 天

MCTSNode 树全部 Go-side. Python 仅发起搜索请求和接收 visit_distribution. 网络 eval 仍走 inference_server RPC (Python 侧).

**总计 5-8 天**, 分 3 个 commit 批次.

### 设计要点

- **Python ↔ Go 边界**: Python 主进程持有 inference_server. Go MCTS worker 通过 Unix socket 向 server 请求 eval.
- **Go 侧需要重实现**: MCTSNode struct, PUCT selection, virtual loss book-keeping, lambda mixing, discovery detection, Dirichlet noise, N_avail IS-MCTS 特化.
- **可以复用**: 已有的 Game.Step() + GetLegalActions() + Snapshot/Restore.
- **正确性验证**: 每阶段对比 Python 版 visit_distribution 一致性 (seed 对齐).

### 不做的事 (用户明确拒绝)

- 不减少 n_rollouts (保持 200)
- 不做 tree reuse (保持每次搜索重建树, 正确性严格)
- 不考虑 L4 (ONNX Go 推理) —— 双栈维护代价不值

---

## 2026-04-19 追补: 重新审视 L3 ROI + 详细决策清单

### 实测后的 ROI 修正

L1 实测 3.8× per-rollout speedup (`tools/bench_rollout.py`), 比理论 38× 差一个量级. 用实测重算 Amdahl (team_size=2, rollout 占 54%):

| 方案 | per-rollout | 相对 baseline |
|---|---|---|
| Baseline (pre-L1) | 35.9 ms | 1.0× |
| **L1 (已完成)** | 21.6 ms | **1.66×** |
| + L3 (Go tree) | 17.2 ms | **2.09×** |
| + L3 + 二进制 IPC | 13.7 ms | 2.62× |

**L3 相对 L1 仅 1.26×**. 因为 eval (32%, 11.5ms) 无法 Go 化 — PyTorch forward 在 Python.

用户坚持 L3 (保持正确性严格, 不做 tree reuse / n_rollouts 降).

### Phase B 详细设计 (5-6 commits, 预估 6-9 天)

完整讨论见 session 记录. 决策矩阵:

#### A 组: 架构基础

| # | 决策 | 原因 |
|---|---|---|
| A1 | cgo callback (非 socket) | 避免 IPC 重写, 复用 inference_server |
| A2 | Root eval 在 Python | 复用 agent.eval_state, 减 Go 边界逻辑 |
| A3 | Dirichlet 在 Python, mixed_prior 传入 Go | numpy 已验证, Go 无需 rewrite |
| A4 | **Slice-based node pool** (非 map) | Go 全栈拥有树, 0 GC 压力, cache 友好 |
| A5 | atomic + RWMutex 混合 | 热路径 (N/W/VL) lock-free, 冷路径 (children) RW 锁 |
| A6 | 共享树 + virtual loss | AZ 标配, 与 Python parity |

#### B 组: 接口协议

| # | 决策 | 原因 |
|---|---|---|
| B1 | JSON config 字符串 | 扩展性 > 20μs parse 成本 |
| B2 | 扁平 C args callback: `(worker_id, game_id, obs*, refs*, pay*, n_legal, out_prior*, out_value*)` | 0 拷贝, 最快 |
| B3 | C array (visits, value) + JSON (profile) | hot path 直传, profile 容忍 JSON |
| B4 | Go pre-alloc obs buffer | Go 拥有引擎 state, Python numpy view 零拷贝 |
| B5 | Per-rollout seed with golden-ratio mixing | 确定性 + 并行可扩展 |

#### C 组: 正确性

| # | 决策 | 原因 |
|---|---|---|
| C1 | 严格 N_avail (IS-MCTS 公式) | 核心算法, 不能简化 |
| C2 | 支持 D1 重扩展 (新 action 中途出现) | 严格复刻 Python |
| C3 | 1 virtual visit (integer) | 保 parity |
| C4 | backup 同步撤 VL + recover() 捕 panic | 性能 + 异常安全 |
| C5 | λ 混合在 Go (rollout 在 Go) | rollout z 只在 Go 有 |
| C6 | 字典序 tie-break | Python 现状 |
| C7 | Q 按 parent.turn 翻转 (必须) | 零和视角 |
| C8 | float32 (W_scaled int64 存) | 带宽 + atomic 兼容 |
| C9 | Terminal 不 expand, 用 z | 显然 |
| C10 | Python 传 mixed_prior + root_value (A2) | 已定 |

#### D 组: 实施范围

| # | 决策 | 原因 |
|---|---|---|
| D1 | 跳过 discovery 检测 (D13) | 当前训练未使用, 未来补 |
| D2 | 完整 MCTSProfile 镜像 | 代价低 (<1ms/search), 诊断必需 |
| D3 | 返错码 + err_buf (长 1024) + recover panic | cgo 友好, 错误信息完整 |
| D4 | 保留 Python 版作 fallback | 双栈短期, parity 测试参考; 连续 2 次 run 无回归后删 |
| D5 | TOML `cfg.mcts.backend = "go" \| "python"` | 和 config 模式一致 |

#### E 组: 测试 / 交付

| # | 决策 | 原因 |
|---|---|---|
| E1 | 3 层 parity (单 rollout / 单 search / selfplay) | bottom-up 定位 bug |
| E2 | par=1 严格 seed-aligned + par>1 top-1 agreement > 95% | 并发引入非确定性 |
| E3 | 50g smoke with games_per_arena=25 (强制 arena 触发) | 快反馈 + 换章验证 |
| E4 | 5-6 commits 按组件: node/puct/backup → parallel → capi → tests → docs | review 分组 |

### Phase B 落地步骤 (修正版)

| 步 | 内容 | Commit 标题 | 状态 |
|---|---|---|---|
| 1 | `gicg_mcts/` package skeleton: node + config + puct + backup + pool | `mcts: Phase B step 1 — Go kernel foundation` | ✅ shipped (0c5ec3e) |
| 2 | 并发安全: virtual loss atomic + goroutine pool + shared tree | `mcts: Phase B step 2 — parallel rollout coordinator` | ✅ shipped (e2ae7bf) |
| 3 | Integration: rollout + determinization + λ + eval via cgo callback | `mcts: Phase B step 3 — engine integration foundation` → `step 3b — runOneRollout impl` | ✅ shipped (1e40069, 52e06b2) |
| 4 | capi 包装: MCTSSearch + Python ctypes 绑定 | `mcts: Phase B step 4 — cgo wrapping + Python binding` | ✅ shipped (28dc676) |
| 5 | Backend flag + selfplay routing + smoke parity tests | `mcts: Phase B step 5 — backend flag + selfplay routing` | ✅ shipped (dbd0b93) |
| 6 | 文档 + cleanup | `mcts: Phase B step 6 — docs + shipped status` | ✅ shipped (this commit) |

**实际工时**: 2 天单日会话 (vs 7 天预估) — 主要省时点是 ROI 复算确认不做 L3 ONNX，以及 Phase A (L1 rollout Go 化) 提前落地让 Phase B 只需 wrap 已有 random_rollout capi.

### 决策包位置 (Post-ship 参考)

运行路径:
- `[mcts] backend = "go"` in TOML → `training/selfplay.py:150-155` 路由到 `training/mcts_go.py::mcts_search_go`
- Python 负责: 根节点 eval + Dirichlet noise + 每局 N 次 determinization 采样
- Go 负责: 整棵树, descent + PUCT + VL + 随机 rollout + backup
- Leaf eval 通过 cgo callback 回到 Python → InferenceClient → inference_server

关键文件:
- `gicg_mcts/` (Go package, ~1100 行): node/pool/puct/backup/rollout/search
- `gicg_engine/capi/mcts_search.go`: MCTSSearch C export + CFUNCTYPE callback
- `training/mcts_go.py`: Python 入口 (mcts_search 签名兼容)
- `training/mcts.py::MCTSConfig.backend`: "python" | "go"
- `configs/smoke_go.toml`: 50g smoke 配置

## 验证计划

Level 1 完成后的验证：

1. **正确性**：Go rollout 和 Python rollout 在相同种子下产生相同胜者
2. **性能**：对比 MCTS search 总时间（预期 rollout 环节 10-50x 加速）
3. **训练影响**：smoke run 确认 loss 曲线和 gauntlet 无回归

## 依赖

- C1v4 训练完成（确认退火策略有效）
- profiling 确认 random rollout 在总 MCTS 时间中的占比（需要 C1v4 的 profiling 数据）

## 2026-04-19 追补: Phase D 并发架构 + D1 处理对齐

### 背景

Phase B step 4 上线后发现:Go backend 单 worker 下比 Python 基线慢 ~15%，
根因是 "D1 reeval" —— 已展开节点遇到新 determinization 带来的新合法 action
时,原实现发一次网络 RPC 取 prior。Go 多 goroutine 并发下,不同 goroutine
独立 determinization,各自触发独立 D1 → 比 Python 单线程 incremental 多
~40% eval RPC。

### 尝试的路径

| 方案 | 5g 1-worker | per-rollout | 说明 |
|---|---|---|---|
| 原 Phase D (reeval 无 dedup) | 150s | 4.03ms | 并发重复最多 |
| cond-var dedup reeval | 143s | 4.13ms | 和 Python sync 对齐 |
| aggregation window | 164-175s | 3.85-4.00ms | follower 几乎 0 → 窗口死代码 |
| **skip D1 + uniform prior** | **127s** | **2.95ms** | **和 Python async 对齐** |
| Python async baseline | 143s | 3.58ms | production |

### 关键发现:Python async 的 D1 处理方式

仔细验证 `training/mcts.py`:
- **sync `mcts_search`**(training/mcts.py:785):D1 调 `_eval_leaf` 取 network
  prior。严格。
- **async `mcts_search_parallel`**(training/mcts.py:946):D1 在
  `_descend_with_vl` 用 `prior=1.0/n` uniform placeholder append。**从不做
  reeval RPC**。`_commit_parallel_rollout` 只 overwrite **CURRENT leaf** 自己
  的 children 的 placeholder(非 D1-added ancestor children)。

**production 走的是 async path**(`training/selfplay.py` 的
`parallel_rollouts > 1 + InferenceClient` 分支)。

结论:**Go "skip D1 + uniform prior"(方案 A)和 Python async 正确性等价**,
不是"近似"。原 Phase D 的 reeval 比 Python async 更严格,是 over-engineering。

### 最终实施 (Phase D.1)

- `gicg_mcts/rollout.go`: D1 分支走 `addNewActionsUniform`(uniform placeholder)
- 删除 aggregation window 基础设施(`reevalSlot`、`reevalAddChildrenAggregate`、
  `buildEvalRequestForActions`、`reevalPending`、Profile 的 `Reeval*` 字段)
- 保留:`hasNewActions` 门控、Phase D 的 multi-goroutine + dispatcher 架构、
  split send/recv callback

### Tier 1+ 延迟项(不实施,归档)

- **Lazy D1 with N_avail threshold**:D1 child 累积 `N_avail ≥ T` 且未 expanded
  时发 prior-only RPC overwrite。小 parallel 下效果不明显。
- **Eval result LRU cache**:key `(static_obs, dyn_obs, legal_ids)` hash,
  dedup 跨 rollout 重复 state。需实测命中率。
- **Over-expansion at first expand**:首次展开枚举 information-set 全集,
  彻底消除 D1 触发。需 `gicg_engine` 提供 "possibly-legal action enumerator"。
- **Separable state + action network**:encode(state) + score(action),缓存
  encoding。需 ML team 重训练。
- **Wave-based synchronized rollouts**:barrier + batch=N。GPU batch-bound
  才有收益。

优先级排序见 `/Users/redcontritio/.claude/plans/wobbly-puzzling-peach.md`。
