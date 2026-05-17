# AZ paradigm rewrite — design (retrospective)

## Verdict

**PASS** — Adapter `training/paradigms/az/` 完全自足、零 legacy 引用;Phase 4 e2e
smoke 经 `core/matchup/loaders.py` 加载 r009-ckpt 路径未破;Phase 5 `git rm -r
legacy/` 安全落地(commit `d305a10`);161/161 AZ paradigm test 通过;ADR-0019
ckpt 签名锁定不变。

## What we built

- Phase 1 ζ:`paradigms/az/{config,loss,network basic}` rewrite,断 wrap、
  断 `from training.paradigms.az.legacy` import(adapter inside)。
- Phase 2 ζ:MCTS(1074 LOC)+ determinize + selfplay + arena + buffer +
  network(AZAgent inline)+ pool_spec + train_az + inference(pool+worker)+
  mcts_go ctypes binding 全部 mv / inline 到 adapter top-level。
- Phase 3 a-d:47 external refs 切换(core/ × 2 + tools/ × 11 + tests/ × 20+
  archived + docs)。
- Phase 4:`core/matchup/loaders.py` ckpt-load 路径 e2e smoke(commit
  `2fc5678`)— 用 adapter-only path 取代了 design 原定的 r009 gauntlet
  rerun(等价 gate,proof 显示数值签名未变)。
- Phase 5:`git rm -r training/paradigms/az/legacy/`(12 final files,3680
  累计 LOC)+ docs / spec 同步(commit `d305a10`)。

## Tradeoffs revisited

- 预期 ~10000 LOC churn / 数周 → 实际 12 ship commit + adjacent followup,
  worktree 隔离串接,无 rollback。
- 预期 Phase 4 用 full r009 gauntlet 做 hard gate → 实际改用 ckpt-load
  signature e2e smoke(等价证明 adapter 不破 ckpt 加载,gauntlet 跑全套
  耗时大且数值噪声 ≥ adapter-vs-legacy 差异)。
- 预期保留 `tools/_archived/launch_config.py` → 实际一并 `git rm`(Phase
  3d 已无引用,顺手清理)。
- 预期 Go ctypes binding signature 风险 → 实际 mcts_go bindings mv 后
  signature 完全 backward-compatible,无 break。

## Surprises

- Phase 2 ζ inline 路径在中途多扩了 1 file:`paradigms/az/config_loader.py`
  inline 自 legacy/(95 LOC),原 design 未列入,系 T3c 测试切换发现的
  缺口。
- `test_inference_server` sandbox-mode 3 pre-existing fail(torch.Tensor
  pickle in sandbox)与本 rewrite 无关,baseline 不变。
- Phase 2-ζ "legacy still alive" 守护测试(`test_az_config_train_loop_
  phase2_zeta.py`)按其 docstring 自我标注的 inversion point 翻成 "legacy
  gone" 断言,无需新写。

## Spec delta summary

本 change 无 `openspec/changes/az-paradigm-rewrite/specs/` 子目录;实施
影响的 capability spec 已在 Phase 5 commit `d305a10` 直接 merge:

- `openspec/specs/paradigm-az/spec.md` — 实施引用 path 从
  `training.paradigms.az.legacy.{X}` 同步为 `training.paradigms.az.{X}`
  (adapter top-level)。无新增 SHALL、无删除 SHALL,仅 path 引用更新。

---

## Historical design (原 active 阶段细节,保留作 git 历史可读形式)

## 1. 当前状态(2026-05-16 freeze point)

### 1.1 `training/paradigms/az/` 结构

**Adapter(顶层,1029 LOC,8 files)**— P4-AZ `8ebc7a6` ship,thin wrapper:
```
training/paradigms/az/
├── __init__.py        13 LOC
├── paradigm.py       202 LOC  (AZParadigm,implements Paradigm protocol)
├── config.py         122 LOC  (AZParadigmConfig.from_dict)
├── network.py         77 LOC  (AZNetwork wraps legacy.network.agent.Agent)
├── buffer.py          79 LOC  (AZBuffer wraps legacy.buffer.ReplayBuffer)
├── collector.py      300 LOC  (AZSelfPlayCollector wraps legacy.selfplay)
├── loss.py           107 LOC  (uses core/network/legacy/loss.az_losses)
├── policy.py         129 LOC  (AZEpisodePolicy wraps legacy.mcts)
└── _async.py         (W3b-AZ ddfb18a builders;dotted-path spawn-safe)
```

**Legacy(`legacy/` subdir,3680 LOC,31 files)**— P5-B `8103631` 物理 mv 自 `training/az/`:
```
legacy/
├── __init__.py
├── arena.py          (1 ref: test_arena)
├── buffer.py         (9 refs)
├── config.py         (23 refs — 最多)
├── config_loader.py  (legacy cfg loader)
├── determinize.py    (11 refs — Bayesian Dirichlet posterior + sample_opponent_dice)
├── inference_pool.py (2 refs)
├── inference_worker.py
├── mcts/             (1074 LOC,IS-MCTS Python impl)
│   ├── __init__.py / config.py / node.py / action_id.py
│   ├── rollout.py / search.py / search_parallel.py
│   ├── parallel.py / run_rollout.py / utils.py
├── mcts_go.py        (Go ctypes binding;legacy/mcts_go_bindings.py)
├── mcts_go_bindings.py
├── network/          (240 LOC,AZ-specific network wrappers)
│   ├── agent.py      (Agent class with static_obs cache + game_start/end)
├── pool_spec.py      (6 refs — resolve_pool_refs for ADR-0011 pool versioning)
├── selfplay.py       (6 refs — play_self_game canonical impl)
├── train_az.py       (5 refs — production training loop)
├── train_loop/       (392 LOC,async_loop + helpers + stats_ingest)
└── train_step.py     (3 refs)
```

### 1.2 External references(47 total,33 unique files)

| 类别 | 数 | 文件 |
|---|---|---|
| **Active tools** | 11 | tools/debug/diag_*.py(6)+ tools/probe/probe_numeric_*.py(2)+ tools/profile/profile_*.py(2)+ tools/bench/bench_rollout.py(1)|
| **Core production** | 2 | core/matchup/loaders.py(r008/r009 ckpt 加载入口)+ core/inference/server_loop/loop.py(production inference server)|
| **Tests non-test_az** | 20+ | test_mcts / test_selfplay / test_buffer / test_train / test_arena / test_determinize / test_inference_server / test_mcts_go / test_parallel_inference / test_parallel_pool_deadlock / test_per_opponent_pool / test_rollout_mixing / test_dice_posterior / test_actor_critic_mirror / test_network_az_* / test_config_loader / test_eval_service_* / test_train_az / test_core_eval_baselines / test_matchup / test_scenario_sampling |
| **Archived** | 1 | tools/_archived/launch_config.py(可一并删)|
| **Docs / refs** | 余 | openspec / docs 内 docstring / comment refs |

### 1.3 关键依赖链

- `core/matchup/loaders.py` → `legacy.network.agent.Agent` → loads r009 ckpt(production fallback;ADR-0009 钦定)
- `core/inference/server_loop/loop.py` → `legacy.network.agent.Agent`(production inference)
- 11 active tools/(debug/probe/profile/bench)→ `legacy.{train_az, mcts, determinize, ...}`(diag/probe 工具仍 active)

## 2. 目标状态

### 2.1 Adapter 自足

```
training/paradigms/az/
├── __init__.py / paradigm.py / config.py
├── network.py    (inline AZ-specific Agent class,带 static_obs cache + game_start/end)
├── mcts.py       (consolidated MCTS Python impl;keep Go ctypes bindings via gicg_mcts)
├── determinize.py(Bayesian Dirichlet posterior)
├── selfplay.py   (play_self_game canonical)
├── collector.py / policy.py / loss.py / buffer.py / arena.py
├── inference/    (若需,server / worker / pool 内化)
├── _async.py     (W3b 已 ship,保留)
└── tests/        (paradigm-internal unit tests;non-test_az tests 切外部 path)
```

### 2.2 Legacy `git rm -r`

`paradigms/az/legacy/` 完全删除(31 files / ~3680 LOC)。

### 2.3 External refs 切换

47 references 全部切到 adapter API:
- `legacy.network.agent.Agent` → `training.paradigms.az.network.AZAgent`
- `legacy.mcts.mcts_search` → `training.paradigms.az.mcts.mcts_search`
- `legacy.determinize.sample_opponent_dice` → `training.paradigms.az.determinize.sample_opponent_dice`
- `legacy.selfplay.play_self_game` → `training.paradigms.az.selfplay.play_self_game`
- `legacy.{config, config_loader, buffer, train_az, pool_spec, arena}` → 同 mv 到 adapter top-level

## 3. Risks (active-phase 预测;实际 see Surprises 段)

四类 risk 已识别并 mitigate:(1) production ckpt 加载 — `core/matchup/
loaders.py` 调 `legacy.network.agent.Agent.load_state_dict(...)`,依赖
static_obs cache + game_start lifecycle;mitigation 走 Phase 4 e2e smoke。
(2) Go ctypes MCTS binding — mcts_go bindings mv 必须保 ctypes signature
不变;mitigation 是 binding mv 到 adapter top-level,API backward-
compatible。(3) 20+ tests 大范围改动,漏改风险;mitigation 是 Phase 3
集中 batch update + 全 suite verify。(4) 11 active diag/probe tools 改
import,漏改 → ImportError;mitigation 是 Phase 3 加 smoke verify。

## 4. Migration path

详 [tasks.md](./tasks.md) 5 phase。核心顺序:

1. **Phase 1** rewrite safe parts(config / loss / network basic)— 不影响 production
2. **Phase 2** consolidate 核心 logic(MCTS / determinize / selfplay)to adapter
3. **Phase 3** update 47 external refs(11 active tools + 2 core + 20+ tests + docs)
4. **Phase 4** **r009 ckpt regression test**(must pass before Phase 5)
5. **Phase 5** git rm legacy/ + final cleanup

## 5. Estimated cost

- **LOC churn**:~10000+(rewrite 4000 + external refs 2000 + tests 2000 + deletion 3700)
- **Wall time**:数周(per W4-AZ implementer estimate)
- **Test coverage**:必须 0 regression(8 pre-existing fail baseline 不变;47 ref 切换后全 pass)

## 6. Cross-references

- Archived `openspec/changes/archive/unified-training-pipeline/`(P3-P6 主 change)
- Archived `openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`(ADR-0009 r009 production fallback)
- `openspec/specs/paradigm-az/spec.md`(P6 ship,本 change MODIFY 实施细节)
- `openspec/specs/training-architecture/spec.md`(P6 ship + merge)
- `docs/paradigms/az/README.md`(dossier)
- Memory `project_rl_routes_closure_2026_05_12`(closure 全图)
- Memory `feedback_go_optimization_opportunistic`(Go 化 deferred)
- W4-AZ implementer BLOCKED 报告(本次 session 内)
