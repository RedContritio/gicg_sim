---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: env-factory-unification
---

# Design — env-factory-unification

## 1. Architecture

### 1.1 Canonical signature

```python
# training/core/env_factory.py(rewrite)
from typing import Any, Callable, Optional
from gicg_env import GicgEnv

def make_env_factory(
    cfg: Any,
    obs_config_json: Optional[dict],
    master_seed: int,
) -> Callable[[int], GicgEnv]:
    """Build paradigm-agnostic env_factory(game_idx) → GicgEnv.

    Args:
        cfg: Must expose `cfg.scenario` (ScenarioConfig from
            `training.core.scenario`). Other cfg fields are NOT read.
        obs_config_json: ObsConfig.to_engine_json() dict, or None.
            None = engine 默认(all-on shuffle + include_char_skill_refs).
            AZ caller pass `cfg.obs.to_engine_json()`;
            DMC / CFR / BC caller pass None(无 ObsConfig 字段)。
        master_seed: int base seed; per-game seed = master_seed + game_idx.

    Returns:
        env_factory(game_idx) → reset()-ed GicgEnv。
    """
    def env_factory(game_idx: int) -> GicgEnv:
        seed = master_seed + int(game_idx)
        env = GicgEnv(
            cfg.scenario.team_0,
            cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=seed,
            data_dir=cfg.scenario.data_dir,
            obs_config=obs_config_json,
            max_rounds=cfg.scenario.max_rounds,
            fix_dice=cfg.scenario.fix_dice,
            obs_mask=cfg.scenario.obs_mask,
            deck_padding=cfg.scenario.deck_padding,
            pool=cfg.scenario.pool,
        )
        env.reset(seed=seed)
        return env

    return env_factory
```

设计要点:

- **3 arg 全 required**,无 `master_seed=None` default — 避免 magic
  seed extraction(legacy 2-arg form 默认从 `cfg.meta.seed` 取,但
  AZ 用 `cfg.seed` 不是 `cfg.meta.seed`,这种 dual schema 让
  default 不可能正确;explicit 解决)
- **obs_config_json `None` semantics**:engine 接受 `None`
  (gicg_env/_engine_lifecycle.py:168 `if obs_config is not None`)
  默认全开 shuffle + include_char_skill_refs
- **cfg 只读 `cfg.scenario`** — 不再耦合 `cfg.obs` 或 `cfg.seed` /
  `cfg.meta.seed`,paradigm-agnostic 边界更清
- `data_dir` 不再有 `'data'` 默认值后缀(`tools/run.py` 内嵌版本之前
  补 `or 'data'`)— 由 caller 在 `cfg.scenario.data_dir` 处显式设置;
  `ScenarioConfig.data_dir: Optional[str] = None`,engine 自有 default
  resolution

### 1.2 Call site migration table

| Site | Before | After |
|---|---|---|
| `paradigms/az/train_loop/async_loop.py:69` | `env_factory = make_env_factory(config)` (1-arg) | `env_factory = make_env_factory(config, config.obs.to_engine_json(), master_seed=config.seed)` |
| `training/tests/test_scenario_sampling.py:210` | `factory = make_env_factory(cfg)` | `factory = make_env_factory(cfg, cfg.obs.to_engine_json(), master_seed=cfg.seed)` |
| `tools/run.py:81` | `env_factory = _build_env_factory(cfg)` (inline) | `env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)` + 删 `_build_env_factory` |

### 1.3 File operations

- `git rm core/env_factory_legacy.py`
- Rewrite `core/env_factory.py`
- New `training/tests/test_env_factory_unified.py`
- Edit 3 call sites
- Edit `tools/run.py` import + delete `_build_env_factory`
- Edit `openspec/specs/training-architecture/paradigm-onboarding.md`
  § 3 + § 9 (revision triggers)

## 2. Tradeoffs

### 2.1 Option A — Canonical 2-arg + master_seed kwarg(REJECTED)

`make_env_factory(cfg, obs_config_json, *, master_seed=None)` 默认从
`cfg.meta.seed` 取。

**Pros**:caller 不需 thread seed,minor convenience。
**Cons**:AZ legacy schema 用 `cfg.seed`(non-`meta.seed`),default
无法正确;dual-schema 时代 magic default 必导致一次 silent bug
(漏传 `master_seed=cfg.seed`,fallback 到 `cfg.meta.seed` 不存在 →
AttributeError 或 silent wrong)。**Rejected**:静默错误风险 > 便利收益。

### 2.2 Option B — Canonical 3-arg required(SELECTED)

`make_env_factory(cfg, obs_config_json, master_seed)` 全 required。

**Pros**:无 magic seed,explicit > implicit;符合项目"严格契约" SHALL。
**Cons**:每 call site 多打 `master_seed=...` 一段;3 个 site 都得 thread。
**Verdict**:SELECTED。3 个 site 的多打可承受;契约清晰避免未来
dual-schema 问题。

### 2.3 Option C — Keep both APIs(REJECTED)

Rename `env_factory_legacy.py` → `env_factory_az.py`、保留 2-arg
`env_factory.py`。

**Pros**:0 caller migration;legacy naming 至少改正。
**Cons**:两套并存命名长期混乱;新 paradigm onboarding 时"我该用
哪个"还是模糊;反"统一" goal。**Rejected**:naming patch 不解决
根本问题。

### 2.4 Option D — Builder pattern / EnvFactory class(REJECTED)

```python
class EnvFactory:
    def __init__(self, cfg, obs_config_json, master_seed): ...
    def __call__(self, game_idx) -> GicgEnv: ...
```

**Pros**:可附加 `reset()` / `state_dict()` 等方法。
**Cons**:本 module 0 复杂度需求;factory pattern 是 over-engineering;
现 closure 接口 `env_factory: Callable[[int], GicgEnv]` 与
`EpisodeRunner` 等 collaborator 解耦 OK。**Rejected**:YAGNI。

## 3. Migration

### 3.1 Phase 顺序

1. **T0** propose
2. **T1** verify `ObsConfig.to_engine_json()` 现存(已确认 `training/core/scenario.py:24`)
3. **T2** rewrite `core/env_factory.py` 为 canonical 3-arg
4. **T3** add `training/tests/test_env_factory_unified.py`(3 invariant)
5. **T4** migrate `async_loop.py` (AZ hot path)
6. **T5** migrate `test_scenario_sampling.py`
7. **T6** migrate `tools/run.py` + delete `_build_env_factory`
8. **T7** `git rm core/env_factory_legacy.py`
9. **T8** sync `paradigm-onboarding.md` § 3 + § 9
10. **T9** pytest sweep verify(per CLAUDE.md test convention)+ `pytest -k env_factory` smoke
11. **T10** commits(propose / impl / spec sync)

### 3.2 Async loop seed handling 验证

`async_loop.py:49` 用 `torch.manual_seed(config.seed)` 已经表明
`config.seed` 是 base seed;`async_loop.py:89` `env_seed=config.seed + game_idx` 表明
per-game seed 也用 `config.seed + game_idx`。canonical signature
`master_seed=config.seed` 完全匹配 legacy 行为,无变化。

### 3.3 `tools/run.py` `obs_config=None` 语义

现 `_build_env_factory` 不传 `obs_config`,等价于 engine `obs_config=None`
默认。改用 `make_env_factory(cfg, None, cfg.meta.seed)` 行为 identical。

## 4. Risks

### 4.1 AZ async_loop hot path 回归

**Risk**:async_loop 是 AZ 训练主循环,签名改错可能 import-time fail
或 silent seed mismatch。

**Mitigation**:
- `pytest -k train_az -n 4` smoke pass(`training/tests/test_train_az.py`
  + `test_az_smoke.py` 等)
- 实际 seed transformation 不变(`config.seed + game_idx`),只是
  封装位置变化
- 加 `test_env_factory_unified.py` invariant:同 cfg + 同 obs_json +
  同 master_seed → 同 `env._max_rounds` / `env._fix_dice`(锁定
  scenario-to-env 字段映射)

### 4.2 `cfg.obs.to_engine_json()` 暴露给 caller

**Risk**:caller(`async_loop.py` / `test_scenario_sampling.py`)现
显式调 `.to_engine_json()`,如果 `ObsConfig` 改 method 名,3 site
全断而非 1 site。

**Mitigation**:本 change 不改 `ObsConfig` schema(out of scope);
未来 ObsConfig 改动是另一 change,届时 callers 数量是 spec 边界明示
(symbolic search 可发现)。这是 explicit > implicit 的接受代价。

### 4.3 `tools/run.py` DMC 行为变化

**Risk**:`tools/run.py` 原 `_build_env_factory` 有 `data_dir=cfg.scenario.data_dir or 'data'` fallback;canonical version 不带 `or 'data'`。

**Mitigation**:
- `ScenarioConfig.data_dir: Optional[str] = None`(`scenario.py:41`),
  engine `GicgEnv` 自有 data_dir resolution(默认 './data')
- 若现有 DMC cfg 依赖 `_build_env_factory` 的 'data' fallback,需要在
  config 内显式设 `scenario.data_dir = 'data'`;否则 engine 自行兜底
- Smoke: `pytest -k dmc -n 4` verify

### 4.4 测试 sandbox failure

CLAUDE.md 标 ignore 6 个 sandbox-fail tests(eval_service 系列 +
cfr_worker / cfr_parallel_trainer / inference_server)— 本 change 不
触碰这些 area,不增加新 sandbox 风险。

## 5. Rollback

- 单 commit 实施(T2-T8 可合并),`git revert <commit>` 一步还原
- propose commit 与 impl commit 分开;若 impl 失败可保留 propose
- spec delta 在 specs/ 子目录,archive 前不影响 live spec

## 6. Verification matrix

| Aspect | Method | Pass criterion |
|---|---|---|
| Canonical signature | `pytest training/tests/test_env_factory_unified.py -v` | 3 invariant green |
| Async loop hot path | `pytest -k 'train_az or az_smoke' -n 4` | 同 baseline pass count |
| `tools/run.py` regression | `pytest -k 'dmc' -n 4` 或 `python -m tools.run configs/dmc_stage3_smoke_v2.toml --max-steps 5` (若存) | smoke pass |
| `env_factory_legacy` 残留 | `grep -rn env_factory_legacy --include='*.py' .` | 0 hit |
| Spec invariant 一致 | `tools/_meta/check_openspec_indices.py --staged` | green |

## 7. LOC estimate

| File | Change | LOC delta |
|---|---|---|
| `core/env_factory.py` | rewrite | -42 / +50 |
| `core/env_factory_legacy.py` | rm | -44 / 0 |
| `paradigms/az/train_loop/async_loop.py` | edit import + call | -2 / +2 |
| `training/tests/test_scenario_sampling.py` | edit import + call | -2 / +2 |
| `tools/run.py` | replace inline + import | -27 / +2 |
| `training/tests/test_env_factory_unified.py` | new | 0 / +80 |
| `openspec/specs/training-architecture/paradigm-onboarding.md` | spec sync | -3 / +12 |
| **Total** | | **-120 / +148**(≈ net +28) |
