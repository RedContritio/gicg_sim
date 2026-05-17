# IS-MCTS Go 化迁移 (L1 + L3)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0004-is_mcts_migration.md` at P1-T1)
**Original date:** 2026-04-17 起,L1 + L3 ship 于 2026-04-19
**Original status:** Accepted + Shipped — `[mcts] backend = "go"` 通过 TOML 启用
**Supersedes:** —
**Superseded by:** —

## Why

当前 MCTS 实现在 Python(~1090 LOC `training/mcts.py`),通过 ctypes 调用 Go engine。每 rollout
约 5-10 次 ctypes 调用(根节点)+ 1-3 次/深度层级,200 rollouts × 8 深度 = ~3200 round-trips/decision。

**2026-04-17 实证**(`artifacts/202604170508_profile_smoke/`,par=1, c1, 4 games):
- eval RPC 79.5% (21.8 ms/call) — 主导
- random rollout 14.8% (5.6 ms/call) — rollout 本体 ~15 steps
- env_query/step 占 3-5%
- 纯 UCT 场景(无网络)rollout 占 93.7%,差 6×

**2026-04-18 实证 (team_size=2 C3,80 局 44608s)**:
- rollout 53.9% (19.3 ms) — **从 14.8% 升到 53.9%**,team_size=2 让 n_steps 3.3× → rollout 主导
- eval 32.1% (11.5 ms) — batching 压降
- L1 Amdahl team_size=1 → 1.15-1.30× / team_size=2 → 2.1×
- L3 Amdahl team_size=2 → 2.8×

team_size=2 让 L1 从 "勉强" 变 "必做",L3 从 "不推荐" 变 "高 ROI"。

## What

**5 个迁移层级**:
- L0: 当前(纯 Python MCTS + ctypes)
- L1: Rollout Go 化(`_random_rollout_value` 移入 Go)
- L2: Determinization + 多步 step 批量化
- L3: 完整 MCTS 树 Go 化(PUCT / 虚拟损失 / 树展开 / backup)
- L4: Go MCTS + ONNX inference(消除 Python)

**决策**:分阶段上 L1 + L3,**不**做 L2 / L4(L4 双栈维护代价不值)。用户 2026-04-18 确认:
"把 mcts 完全 go 化, 不减少 rollouts 也不做 tree reuse"。保持算法严格性,换 Go 原生性能。

**Phase A (L1)** — `gicg_engine/capi` 加 `GameRandomRollout(gid, seed, maxSteps)` 单次 ctypes 返终局;
Python `_random_rollout_value` 改单次调用。1 天 ship。实测 3.8× per-rollout speedup → 1.66× baseline。

**Phase B (L3)** — `gicg_mcts/` Go package(~1100 LOC):MCTSNode 树 + PUCT + virtual loss + lambda
mixing + Dirichlet noise + N_avail IS-MCTS。Python 仅发起 search,网络 eval 通过 cgo callback 回 Python
InferenceClient。6 commits,2 天单日 ship(预估 7 天)。

**Phase D.1 (并发 + D1 处理)** — Go backend 多 goroutine 独立 determinization 导致 ~40% 额外 eval RPC。
最终方案:**skip D1 + uniform prior**(对齐 Python async path,不是近似)。删 aggregation window
infrastructure。

## Affected specs

- `mcts-backend` (待建,P1-T2/T6 抽 SHALL invariants 时 backfill)
- `engine-capi` (新加 `GameRandomRollout` + `MCTSSearch` exports)
- `training-architecture` (mcts backend toggle)
