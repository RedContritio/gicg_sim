---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: paradigm-smoke-full-tier
---

# Proposal — paradigm-smoke-full-tier

## 1. Why

Per user 2026-05-17(D-601 in `core-network-generic-promotion` DECISIONS,
revised 2nd time on same day),现 `@pytest.mark.smoke` tier 仅做 single
forward eval probe(D-304 partial)+ BC loss "不增长"(D-305 partial)。

这两个 partial compliance 是 spec invariant A1 的让步,**没有覆盖**:

- Driver 真实 train loop(`tools.run <cfg>` subprocess)是否能跑到 100 step
- `CheckpointManager` auto-save(`should_save` 周期触发)是否真的把
  `ckpt_<step>.pt` 写到 artifacts dir
- `CheckpointManager.try_resume()` 路径是否能 load 已存 ckpt + 继续训练
  + 写出后续 ckpt
- 5 paradigm 是否各自能跑通 production driver 的完整 cycle(不只 protocol
  level 单 forward + backward)

User 显式要求(原话):"我希望提供完整的 smoke 测试,包括 100 steps 训
练,自动保存 ckpt,单独 resume from ckpt 等等。通常跑全量的时候不执行,
而是仅在大版本改动之后才跑,用来验证正确性"。

## 2. What

**5 bullets**:

1. **新 marker `@pytest.mark.smoke_full`** in `pyproject.toml` +
   `addopts = "-m 'not smoke_full'"` 默认排除,opt-in via `pytest -m smoke_full`
2. **新 `training/tests/smoke_full_template.py`** ~80-120 LOC — 3 个
   subprocess helper(`run_paradigm_train_via_driver` /
   `verify_ckpt_files` / `resume_and_continue`),复用 production
   `tools.run` driver + `CheckpointManager`,**不重新发明 save/load/dispatch**
3. **新 `configs/<paradigm>/smoke_full.toml`** × 5(extends 现 `smoke.toml`
   + override `[checkpoint] save_every` to short cadence + bump
   `total_games` / `total_frames` / `total_iterations` 等触发 ≥ 100 step
   train + ≥ 2 ckpt save)
4. **新 `training/tests/test_<paradigm>_smoke_full.py`** × 5 — 每 paradigm
   ~15-20 LOC,subprocess `tools.run <smoke_full.toml>` + 3 assert(ckpt
   files written / metrics.jsonl progressed / resume produces new ckpt)
5. **Spec delta** `training-architecture/spec.md` ADD invariant A1.6
   smoke_full tier 契约,closes D-304(eval probe full episode via driver)
   + D-305(BC loss strict decrease over 100 step)

## 3. Affected specs

- `training-architecture/spec.md` § ADD invariant A1.6(smoke_full tier 契约)
- 主 spec.md 的 invariants 列表无新增条目(A1 现已存在;A1.6 是其 sub-clause)
- 无 paradigm-spec 修改

## 4. Out of scope

- **不动** paradigm 算法 / network / collector 代码 — 全 subprocess `tools.run`
  driver 调用,paradigm 内部 BUG 出现属 paradigm spec 范围,不在本 change 修
- **不动** `@pytest.mark.smoke` 现 5 paradigm smoke 文件(它们继续保持
  60s budget 的 D-304/305 partial compliance,smoke_full 是 second tier)
- **不增** CI 自动跑 smoke_full — opt-in only,user "大版本改动后跑"
- **不做** bit-identical resume weight comparison — 只 functional
  (resume 能 forward + step + 新 ckpt 出现);per D-601 决策 3
- **不修复** 现有 paradigm smoke.toml 跑 `tools.run` 时遇到的 pre-existing
  bug(CFR `max_game_steps` 偏紧 / AZ `card_pool_spec` type mismatch /
  PPO `card_pool=None` / BC 缺 NPZ dataset)— 这些是各 paradigm 自身
  的 production bug,在本 change 用 `pytest.skip(reason=...)` 标记并指
  向后续 follow-up changes

## 5. Decision summary(详 DECISIONS.md)

- **[SF-101] Subprocess `tools.run`,不 in-process**:避免 sys.path / global
  state 污染,与 production 调用一致;startup overhead ~1s/invoke 在
  5-10min budget 内可接受
- **[SF-102] Resume verify = functional,不 bit-identical**:rng state 可
  能轻微 drift,bit-identical 会 flaky;functional(resume → forward → step
  → 新 ckpt 出现)足以 demonstrates load 路径连通
- **[SF-103] smoke_full toml 用 `extends`**:per cfg-toml-restructure-paradigm-scoped
  hybrid structure + `meta.extends` 继承,smoke_full 只 override `[checkpoint]
  save_every` + 拉长 termination 字段
- **[SF-104] 8 min target / 15 min hard cap per paradigm**:5 paradigm
  full sweep ~40 min,符合 user "大版本前跑" cadence
- **[SF-105] 4/5 paradigm smoke `pytest.skip` 标记**(2026-05-17 实施时
  发现):AZ / PPO / CFR / BC 的现有 smoke cfg + `tools.run` 路径有 pre-existing
  非本 change scope bug,DMC 是唯一可端到端跑通的。skip 不算"半成品",
  是 test 真实暴露的契约 gap;follow-up changes 修复各 paradigm 后取消 skip
- **Effort**:~300-400 LOC(per D-601 2nd revision):
  - 5 toml ~150 行 + 5 test files ~75-100 LOC + template ~80-120 LOC +
    pyproject ~5 行 + docs(proposal/design/tasks/spec delta)~150 行
