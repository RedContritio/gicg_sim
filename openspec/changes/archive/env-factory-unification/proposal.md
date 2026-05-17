---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: env-factory-unification
---

# Proposal — env-factory-unification

## 1. Why

post `core-network-generic-promotion` Phase 2F 收尾,DECISIONS log
[D-102] 把 `core/env_factory_legacy.py` rename 推迟到本 follow-up
change。当前状态:

| File | Signature | Callers | Production? |
|---|---|---|---|
| `core/env_factory.py` | `make_env_factory(cfg, obs_config_json, *, master_seed=None)` (2-arg) | **0** (orphan) | NO |
| `core/env_factory_legacy.py` | `make_env_factory(cfg)` (1-arg,读 `cfg.obs`) | 2 (`paradigms/az/train_loop/async_loop.py` + `training/tests/test_scenario_sampling.py`) | YES (AZ async hot path) |
| `tools/run.py` `_build_env_factory` (inline) | hard-coded inline,no obs_config | 1 (unified entry) | YES (DMC / future) |

三个共存 + `legacy` 命名误导(它仍是 production)+ 没有 single source
of truth。Spec 侧 `training-architecture/paradigm-onboarding.md` §3
layout 暗示 `env_factory_legacy.py` 已退役,但实际未退。

`tools/run.py` 内嵌版本是第三个变体 — proposal 时只识别两套,实际是
**三套**。这增加了 reconciliation 范围。

## 2. What

**5 bullets**:

1. 选定 **canonical 2-arg signature** `make_env_factory(cfg, obs_config_json, master_seed)`(详 design.md tradeoff 比较),三个 arg 全 required,无 magic seed extraction
2. Rewrite `core/env_factory.py` 为 canonical 实现,接受 `obs_config_json: Optional[dict]`(`None` = engine 默认 all-on,for DMC 等没有 ObsConfig 的 paradigm)
3. 迁移 **3 个 call sites**:`paradigms/az/train_loop/async_loop.py`、`training/tests/test_scenario_sampling.py`、`tools/run.py` `_build_env_factory` → 都用 canonical `make_env_factory`
4. `git rm core/env_factory_legacy.py`(rename 后 legacy 命名彻底消失;canonical 单一文件)
5. 加 `training/tests/test_env_factory_unified.py` 锁 3 个 invariant(obs_config=None path、obs_config=ObsConfig.to_engine_json() path、master_seed override)

## 3. Affected specs

- `training-architecture/paradigm-onboarding.md` § 9 revision triggers
  + § 3 layout — 标 `env_factory_legacy.py` 已正式退役 + add §
  "env_factory 公共契约" 描述 canonical signature
- `tools-layout/spec.md` —`tools/run.py` 内嵌 `_build_env_factory`
  SHALL be 删除,改用 `core.env_factory.make_env_factory`

## 4. Out of scope

- **不改** `env_factory` 内部 `GicgEnv` 构造逻辑(team_0 / pool /
  fix_dice / obs_mask / deck_padding 这些参数原样转发)
- **不改** `ObsConfig` schema(`to_engine_json()` 保持现状)
- **不改** `tools/debug/diag_*.py` 内的本地 `env_factory` 闭包定义
  — 它们是 ad-hoc debug 工具,不消费 cfg,各自需要不同的 env 配置;
  统一化是 over-engineering,且当前 0 复用价值
- **不引入** factory class / builder pattern — 保持 plain function
- **不改** `actor_process.build_env_factory` 自定义 hook 协议(它是 async
  pipeline 用 path-import 的 callable,非本 module 范围)

## 5. Decision summary

- Canonical: `make_env_factory(cfg, obs_config_json: Optional[dict], master_seed: int)` — 3 arg 全 required,zero magic
- Migration: 3 site,~+30/-50 LOC
- Tests: 1 new file(~80 LOC),3 invariant
- Risk: AZ async hot path 改动需 smoke verify
- Effort: ~5 commits(propose / impl / test / rm / spec sync)
