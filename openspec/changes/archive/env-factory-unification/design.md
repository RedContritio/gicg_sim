---
last_updated: 2026-05-17
status: ARCHIVED
schema_version: 0
change_id: env-factory-unification
---

# env-factory-unification — Design Retrospective

> Archive-time summary (≤ 200 lines per archive cap)。Architecture +
> tradeoff + migration / risk / verification 详节已拆到 `design/` subdir,
> 见 ↓ 索引。

## Verdict

**完整成功** — canonical 3-arg `make_env_factory(cfg, obs_config_json,
master_seed)` 落地;三套 env factory(`core/env_factory.py` orphan +
`core/env_factory_legacy.py` AZ production + `tools/run.py`
`_build_env_factory` inline)收敛为单一 source-of-truth
`training/core/env_factory.py`。3 个 call site 全部迁移,`env_factory_legacy.py`
`git rm`,`_build_env_factory` inline 删除。AZ async hot path smoke pass
no regression,3 invariant test 锁定 canonical 行为(`obs_config=None` path +
`obs_config=ObsConfig.to_engine_json()` path + master_seed override)。

## What we built

- **`training/core/env_factory.py` rewrite** — canonical 3-arg
  signature(cfg / obs_config_json / master_seed),全 required 无 default
  magic;cfg 只读 `cfg.scenario`(ScenarioConfig);返回 closure
  `env_factory(game_idx)` → reset()-ed GicgEnv,per-game seed =
  `master_seed + game_idx`
- **3 call site 迁移**:
  - `paradigms/az/train_loop/async_loop.py` — `make_env_factory(config,
    config.obs.to_engine_json(), master_seed=config.seed)`
  - `training/tests/test_scenario_sampling.py` — 同 AZ 模式
  - `tools/run.py` — `make_env_factory(cfg, None, master_seed=cfg.meta.seed)`
    + 删 `_build_env_factory` inline helper(-27 LOC)
- **`git rm core/env_factory_legacy.py`** — `_legacy` 后缀命名彻底消失;
  canonical 单一文件
- **`training/tests/test_env_factory_unified.py`** new(~80 LOC) — 3
  invariant test 锁:
  - obs_config_json=None path → engine 默认 obs
  - obs_config_json=cfg.obs.to_engine_json() path → AZ 模式
  - master_seed override → per-game seed correctness
- **Spec sync** — `training-architecture/paradigm-onboarding.md` §3.1
  加 canonical signature + 6 SHALL(PA-EF1..6)+ §7.6 加 `_legacy.py`
  后缀禁止 anti-pattern(parent change 已 pre-implement,本 change 锁定
  invariants 主章节)

详 `design/architecture.md`。

## Tradeoffs revisited

- **Option B (3-arg required)选定** ✓ — 实施符合预期:caller 多打
  `master_seed=...` 一段 acceptable(3 site 总 +6 字符),换来契约清晰
  避免 dual-schema(`cfg.seed` vs `cfg.meta.seed`)magic default 必致
  silent bug。Option A (2-arg + magic default)+ Option C (keep both
  APIs)+ Option D (builder pattern) 全 rejected
- **`obs_config_json=None` semantics** ✓ — engine 默认 all-on shuffle +
  include_char_skill_refs(`gicg_env/_engine_lifecycle.py:168` `if
  obs_config is not None`),完全符合 DMC / CFR / BC paradigm 不需要
  paradigm-local ObsConfig 的情况
- **`tools/run.py` data_dir fallback 删除** ✓ — 原 inline 有 `data_dir=
  cfg.scenario.data_dir or 'data'`,canonical version 不带 `or 'data'`;
  实测 `ScenarioConfig.data_dir: Optional[str] = None` + engine 自有
  resolution(默认 `./data`)兜底,DMC smoke 无 regression
- **AZ async_loop seed handling 验证** ✓ — `async_loop.py:49`
  `torch.manual_seed(config.seed)` + `:89` `env_seed=config.seed +
  game_idx` 双重证明 `config.seed` 是 master seed;canonical
  `master_seed=config.seed` 完全匹配 legacy 行为
- **LOC delta**:预期 -120 / +148(net +28),实际接近,新加 test +
  spec sync 抵消 `_legacy.py` 删除 + `_build_env_factory` inline 删除

## Surprises

- **三套并存而非两套**:propose 时只识别 `core/env_factory.py` +
  `core/env_factory_legacy.py` 双 module,实施前 grep 才发现 `tools/run.py`
  内 `_build_env_factory` 27 行 inline 是第三个变体,reconciliation
  范围扩大但仍在单 change scope 内
- **paradigm-onboarding.md §3.1 + §7.6 已被 parent change pre-implement** —
  parent `core-network-generic-promotion` archive 合 spec delta 时已经
  把 canonical signature + 6 SHALL invariants + `_legacy.py` 后缀禁止
  加到 onboarding subtopic;本 change archive 仅需把 SHALL 主章节
  (invariants.md #20-#25)+ 新建 `env-factory.md` subtopic 完成 — M1/M2
  实质 spec delta 在 parent merge 时已落地

## Spec delta summary

本 change 修订 training-architecture capability:

- **training-architecture**:
  - **invariants.md** +6 SHALL #20-#25(PA-EF1..6 canonical signature
    contracts:3 required args / cfg 只读 scenario / obs_config_json=None
    semantic / AZ vs non-AZ 调用模式 / per-game seed 协议 / 单一
    source-of-truth)
  - **env-factory.md** (新 subtopic, 154 行):承接 ADD A1 详节
    canonical signature + 设计要点 + SHALL summary 速查 + 3 类 usage
    examples (AZ / DMC-CFR-BC / per-game seed) + retirement of
    `env_factory_legacy.py` + cross-references
  - **paradigm-onboarding.md** §3.1 + §7.6 (MODIFY M1/M2):
    `env_factory_legacy.py` 退役标完成 + `_legacy.py` 后缀禁止规则
    (实际由 parent change pre-implement,本 change 仅锁定 invariants 引用)
  - **spec.md** Subtopics 索引 8 → 9 + SHALL count 19 → 25 同步 + Status
    section +archive merge entry
- **tools-layout** REMOVE R1: spec 层 no-op(verify `grep
  _build_env_factory openspec/specs/tools-layout/spec.md` 无引用,实施在
  code 侧通过 `tools/run.py` `_build_env_factory` 删除完成)

## 索引

- **[`design/architecture.md`](./design/architecture.md)** — 原 propose-time
  design(canonical signature + 4 option tradeoff + 3-site migration
  table + risk analysis + LOC estimate),归档保留作历史决策依据
