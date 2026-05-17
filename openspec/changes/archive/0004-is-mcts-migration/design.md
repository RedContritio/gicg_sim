# Design (retrospective)

## Consequences

### L1 ship (Phase A)
- `gicg_engine/capi/capi.go` 加 `GameRandomRollout`
- `training/mcts.py::_random_rollout_value` 单次 ctypes
- 实测 per-rollout 35.9ms → 21.6ms (1.66× baseline)
- gauntlet 场景 (无网络 eval) rollout 主导 ~90%,L1 仍 6-10× 加速

### L3 ship (Phase B)
- 新 package `gicg_mcts/` (~1100 LOC),6 commits:
  1. Skeleton: node + config + puct + backup + pool (0c5ec3e)
  2. Parallel rollout coordinator: virtual loss atomic + goroutine pool + shared tree (e2ae7bf)
  3. Integration: rollout + determinization + λ + eval via cgo callback (1e40069 + 52e06b2)
  4. capi wrapping: `MCTSSearch` C export + Python ctypes binding (28dc676)
  5. Backend flag + selfplay routing + smoke parity tests (dbd0b93)
  6. Docs + cleanup
- `[mcts] backend = "go" | "python"` TOML flag — Python 版作 fallback,2 次 run 无 regression 后删

### 决策矩阵关键点

| 组 | # | 决策 | 原因 |
|---|---|---|---|
| A | A1 | cgo callback (非 socket) | 避免 IPC 重写, 复用 inference_server |
| A | A2 | Root eval 在 Python | 复用 agent.eval_state |
| A | A3 | Dirichlet 在 Python,mixed_prior 传入 Go | numpy 已验证 |
| A | A4 | Slice-based node pool (非 map) | 0 GC 压力, cache 友好 |
| A | A5 | atomic + RWMutex 混合 | 热路径 lock-free, 冷路径 RW 锁 |
| A | A6 | 共享树 + virtual loss | AZ 标配, Python parity |
| B | B1 | JSON config 字符串 | 扩展性 > 20μs parse 成本 |
| B | B2 | 扁平 C args callback | 0 拷贝, 最快 |
| B | B3 | C array (visits, value) + JSON (profile) | hot path 直传 |
| B | B4 | Go pre-alloc obs buffer | numpy view 零拷贝 |
| B | B5 | Per-rollout seed with golden-ratio mixing | 确定性 + 并行可扩展 |
| C | C1 | 严格 N_avail (IS-MCTS 公式) | 核心算法 |
| C | C2 | 支持 D1 重扩展 (新 action 中途出现) | 严格复刻 Python |
| C | C3 | 1 virtual visit (integer) | parity |
| C | C4 | backup 同步撤 VL + recover() 捕 panic | 性能 + 异常安全 |
| C | C5 | λ 混合在 Go | rollout z 只在 Go 有 |
| C | C6 | 字典序 tie-break | Python 现状 |
| C | C7 | Q 按 parent.turn 翻转 | 零和视角 |
| C | C8 | float32 (W_scaled int64 存) | 带宽 + atomic |
| C | C9 | Terminal 不 expand,用 z | 显然 |
| D | D1 | 跳过 discovery 检测 | 当前训练未使用 |
| D | D2 | 完整 MCTSProfile 镜像 | 诊断必需,代价 <1ms |
| D | D3 | 返错码 + err_buf + recover panic | cgo 友好 |
| D | D4 | 保留 Python 版作 fallback | 2 次 run 无 regression 后删 |
| D | D5 | TOML `cfg.mcts.backend` | 和 config 模式一致 |
| E | E1 | 3 层 parity (单 rollout / 单 search / selfplay) | bottom-up bug 定位 |
| E | E2 | par=1 严格 seed-aligned + par>1 top-1 > 95% | 并发非确定性 |
| E | E3 | 50g smoke games_per_arena=25 | 快反馈 + 换章验证 |

### Phase D.1 (D1 处理对齐)

Go backend 单 worker 比 Python 慢 ~15%,因 D1 reeval(已展开节点遇新 determinization 新合法 action
时 reeval RPC)。多 goroutine 独立 determinization → ~40% 额外 eval RPC。

实测对比:
- 原 Phase D (reeval 无 dedup): 150s / 4.03ms per-rollout
- cond-var dedup reeval: 143s / 4.13ms
- aggregation window: 164-175s / 3.85-4.00ms (window 死代码)
- **skip D1 + uniform prior: 127s / 2.95ms** — 和 Python async 对齐
- Python async baseline: 143s / 3.58ms

发现 **Python async (production) 走 uniform prior placeholder,不做 reeval RPC**。原 Phase D 的
reeval 比 Python async 更严格,是 over-engineering。最终方案:`gicg_mcts/rollout.go` D1 分支走
`addNewActionsUniform`,删 aggregation window infra(reevalSlot / reevalAddChildrenAggregate /
buildEvalRequestForActions / reevalPending / Profile.Reeval*)。

## Tradeoffs revisited

| 方案 | per-rollout | 相对 baseline | 决策 |
|---|---|---|---|
| Baseline (pre-L1) | 35.9 ms | 1.0× | — |
| L1 (shipped) | 21.6 ms | 1.66× | ✓ |
| + L3 (Go tree) | 17.2 ms | 2.09× | ✓ |
| + L3 + 二进制 IPC | 13.7 ms | 2.62× | not done |

L3 相对 L1 仅 1.26× — 因 eval (32%,11.5ms) 无法 Go 化 (PyTorch forward 在 Python)。用户坚持 L3 保
正确性严格。

**Tier 1+ 延迟项**(不实施,归档):Lazy D1 with N_avail threshold / Eval result LRU cache /
Over-expansion at first expand / Separable state + action network / Wave-based synchronized rollouts。

## References

- `docs/2_decisions/adr-0004-is_mcts_migration.md` (mirror)
- `gicg_mcts/` package (Go MCTS kernel, ~1100 LOC)
- `gicg_engine/capi/mcts_search.go` — MCTSSearch C export + CFUNCTYPE callback
- `training/mcts_go.py` — Python entry (mcts_search 签名兼容)
- `training/mcts.py::MCTSConfig.backend` — "python" | "go" flag
- `configs/smoke_go.toml` — 50g smoke 配置
- `tools/bench_rollout.py` — L1 per-rollout speedup 实测
- `/Users/redcontritio/.claude/plans/wobbly-puzzling-peach.md` — Tier 1+ 延迟项优先级
