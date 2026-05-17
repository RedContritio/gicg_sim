---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: paradigm-smoke-full-tier
---

# DECISIONS — paradigm-smoke-full-tier

> Autonomous implementation decisions(user 显式授权"reasonable call and
> continue")。每条 [SF-N] 是 spec delta + impl 的依据,archive 时进
> training-architecture spec 主文档。

## SF-101 — Subprocess `tools.run`,not in-process driver call

- **Decision**:smoke_full template 用 `subprocess.run([sys.executable,
  '-m', 'tools.run', ...])` 调度 paradigm 训练,**不**直接 in-process
  `from tools.run import main; main(...)`。
- **Why**:
  - 避免 sys.path 污染(在 pytest collection 中 import paradigm 会触发
    全套 module load,与单独 subprocess 行为不一致)
  - 与 production 调用 1:1(`docker compose run train python -m tools.run`)
  - PyTorch global state(MPS device alloc / DataLoader workers)在
    pytest re-entrant 时易出现 deadlock,subprocess 完全隔离
- **Trade-off**:每 subprocess startup ~1-2s 开销(Python + torch import);
  5 paradigm × 2 invoke = ~10-20s 总开销,在 5-10min budget 内可接受
- **Spec impact**:A1.6.2 + A1.6.3 表述"subprocess-invoke"明确

## SF-102 — Functional resume verify,not bit-identical weight comparison

- **Decision**:resume test 只 assert "subprocess exit 0 + 新 ckpt 出现",
  **不** assert "resumed network state_dict equals saved state_dict bitwise"。
- **Why**:
  - RNG state restore 在 CheckpointManager 已 cover,但 numpy / torch RNG
    在不同 paradigm 内部还有 process-local 状态(MCTS rollout / collector
    seeding),resume 后 1 个 step 已可能产生微 drift
  - bit-identical assertion 会 flaky(尤其 MPS / multi-thread numpy)
  - target 是"load 路径连通 + train continuation functional",functional
    verify 已 demonstrates
- **Spec impact**:A1.6.3 显式标 "functional verification only"
- **Follow-up**:若未来加 "deterministic resume" spec invariant(强 contract),
  可单独 propose change `deterministic-resume-contract`

## SF-103 — smoke_full toml 用 `meta.extends` 继承 smoke.toml

- **Decision**:每 `configs/<paradigm>/smoke_full.toml` 用
  `meta.extends = "smoke.toml"` 继承同 paradigm 的 smoke.toml,只
  override `[checkpoint] save_every` + paradigm-specific terminus + run_label。
- **Why**:
  - `cfg-toml-restructure-paradigm-scoped`(刚 ship)`meta.extends` 已支持
    路径 relative to cfg dir(`_load_with_extends` in loader.py:106)
  - smoke.toml 的 scenario / shape / paradigm cfg 全可复用,差异只是
    跑得久一点 + 多存 ckpt — `extends` 是最小 diff
  - 任何 smoke.toml 改动自动 propagate 到 smoke_full,DRY
- **Spec impact**:A1.6.6 显式要求 extends + 只 override 3 类字段
- **Alternative considered**:inline 复制全部 smoke 内容 → reject,DRY
  违反 + 维护负担

## SF-104 — 8 min target / 15 min hard cap per paradigm

- **Decision**:smoke_full template 内 `timeout=900s`(15 min)hard cap;
  target wall ~5-8 min per paradigm。
- **Why**:
  - user 显式"~5-10 min wall per paradigm"
  - 15 min hard cap 留 buffer 给 CI variance(MPS / OMP / disk I/O)
  - 全 5 paradigm sweep ~25-45 min 符合"大版本前跑"cadence
- **Spec impact**:A1.6.5 显式标 "≤ 15 min hard cap, ≤ 8 min target"

## SF-105 — 4/5 paradigm tests use `pytest.skip` due to pre-existing bugs

- **Decision**:DMC 是唯一**当前**能跑通 `tools.run configs/dmc/smoke.toml`
  到完成的 paradigm。其余 4 个(AZ / PPO / CFR / BC)各自被 pre-existing
  paradigm 内 bug 阻塞,smoke_full test 用 `pytest.skip(reason=...)` +
  指向 follow-up change id 标记。
- **Findings**(实施时跑 `tools.run configs/<X>/smoke.toml` 暴露):
  - **AZ**: `training/paradigms/az/collector.py:72` `_card_pool_spec =
    resolve_pool_refs(cfg.scenario)` 返回 `dict[int, list[int]]`,但
    `play_self_game` 把它当 `CardPoolSpec` 传给 `sample_hidden_state`,
    后者 call `.sample_opponent_deck()` → `AttributeError`。正确做法
    是 wrap `make_pool_spec(scenario, resolve_pool_refs(scenario))`。
    follow-up change id: **`az-pool-spec-type-fix`**
  - **PPO**: `training/paradigms/ppo/_rollout.py:130` `list(getattr(scen,
    'card_pool', ()))` — 当 `scen.card_pool is None`(smoke scenario 未
    define),`list(None)` raises TypeError。should be `list(getattr(scen,
    'card_pool', None) or ())`。follow-up: **`ppo-rollout-card-pool-none-fix`**
  - **CFR**: `configs/cfr/smoke.toml` 的 `[paradigm.cfr.traversal]
    max_game_steps = 30` 不足以让一次 traversal 完整跑完,
    `os_sampling.py:34` raises `RuntimeError`。可能是 cfg 偏紧 OR
    traversal 早期 termination 逻辑 bug。follow-up:
    **`cfr-smoke-max-steps-fix`**
  - **BC**: `configs/bc/smoke.toml` 的 `[paradigm.bc] dataset_path = ""`,
    需要 user 通过 `--override paradigm.dataset_path=<npz>` 注入。
    smoke_full 缺自动生成 NPZ dataset fixture 的机制。follow-up:
    **`bc-smoke-dataset-fixture`**(可能 reuse `tools/dataset/gen_bc.py`)
- **Why skip not fail**:
  - 本 change scope 明示"不修 paradigm code";修复 4 个 paradigm
    bug × ~50-200 LOC each = ~200-800 LOC,远超本 change 300-400 LOC 预算
  - skip 是"诚实暴露 spec contract gap"— smoke_full tier 暴露了
    "paradigm production driver 是否端到端 functional" 这个 contract,
    DMC pass + 4 skip 显示 contract 的覆盖现状,迫使 follow-up 修
  - 等 4 个 follow-up changes ship 后,逐个 remove `pytest.skip` 即可激活
- **Why not just leave smoke_full only for DMC**:不对称 — A1 invariant
  要求 5 paradigm 对称 smoke 覆盖,smoke_full A1.6 应同等要求 5 paradigm
  对称(test 文件全建,skip 是 runtime decision,不破 spec)
- **Spec impact**:A1.6.7 显式允许 `pytest.skip` + 要求 skip message 指
  follow-up change id;不算 spec violation

## SF-106 — `--override checkpoint.artifacts_root=<tmp_path>` 隔离测试 ckpt

- **Decision**:smoke_full test 把 `checkpoint.artifacts_root` override 到
  pytest `tmp_path`,artifacts 不污染 repo 的 `artifacts/`。
- **Why**:
  - pytest tmp_path 自动 cleanup(避免 disk leak)
  - 多次 test 不互相 stomp(同 timestamp 撞)
  - production artifacts 不被 test 数据污染
- **Implementation**:`tools.run` 已支持 `--override key.path=value`,
  smoke_full template 拼好 override flag 即可
- **Spec impact**:无;实施 detail
