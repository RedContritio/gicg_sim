---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: env-factory
---

# Training Architecture — env_factory 公共契约

> 本 subtopic 承载 `training/core/env_factory.py` 的公共 API 契约 +
> 6 SHALL invariant 详节 + paradigm 调用模式。SHALL 锚定见
> [`./invariants.md`](./invariants.md) #20-#25(env_factory 契约)。
> Paradigm-onboarding §3.1 layout 引用此 subtopic 作权威源。

## 1. 章节由来

Added by `env-factory-unification` (archived 2026-05-17),解决三套
env factory 并存(`core/env_factory.py` 2-arg orphan + `core/env_factory_legacy.py`
1-arg production + `tools/run.py` `_build_env_factory` inline)的 single
source-of-truth 问题。canonical signature 收敛到 `training/core/env_factory.py`
唯一文件。

## 2. Canonical signature

```python
# training/core/env_factory.py
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
```

### 2.1 设计要点

- **3 arg 全 required**,无 `master_seed=None` default — 避免 magic
  seed extraction(legacy 2-arg form 默认从 `cfg.meta.seed` 取,但
  AZ 用 `cfg.seed` 不是 `cfg.meta.seed`,dual schema 让 default 不可
  能正确;explicit 解决)
- **obs_config_json `None` semantics**:engine 接受 `None`
  (`gicg_env/_engine_lifecycle.py:168` `if obs_config is not None`)
  默认全开 shuffle + include_char_skill_refs
- **cfg 只读 `cfg.scenario`** — 不再耦合 `cfg.obs` / `cfg.seed` /
  `cfg.meta.seed`,paradigm-agnostic 边界更清

## 3. SHALL contracts(summary)

完整 SHALL 措辞见 [`./invariants.md`](./invariants.md) #20-#25;以下是
summary 速查:

| # | 锚 | 概要 |
|---|----|------|
| 20 | PA-EF1 | 3 arg 全 required,无 default magic |
| 21 | PA-EF2 | cfg 只读 `cfg.scenario`,paradigm-agnostic 边界 |
| 22 | PA-EF3 | `obs_config_json=None` 合法,= engine 默认 obs |
| 23 | PA-EF4 | AZ pass `cfg.obs.to_engine_json()` |
| 24 | PA-EF5 | per-game seed = master_seed + game_idx;GicgEnv 参数从 scenario 转发 |
| 25 | PA-EF6 | 唯一 `make_env_factory` symbol;无并行 `_legacy`/`_v2` 版本 |

## 4. Usage examples

### 4.1 AZ paradigm(持有 ObsConfig)

```python
# training/paradigms/az/train_loop/async_loop.py
from training.core.env_factory import make_env_factory

env_factory = make_env_factory(
    config,
    config.obs.to_engine_json(),
    master_seed=config.seed,
)
```

AZ 持有 `cfg.obs: ObsConfig`(legacy schema `cfg.seed` 顶层),显式调
`.to_engine_json()` 转 dict。

### 4.2 DMC / CFR / BC paradigm(无 ObsConfig)

```python
# tools/run.py — paradigm-agnostic 入口
from training.core.env_factory import make_env_factory

env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)
```

`obs_config_json=None` 触发 engine 默认 obs(all-on shuffle +
include_char_skill_refs)— 适用于不持有 ObsConfig 字段的 paradigm。

### 4.3 Per-game seed 协议

```python
env = env_factory(game_idx=0)   # seed = master_seed + 0
env = env_factory(game_idx=42)  # seed = master_seed + 42
```

closure 返回 reset()-ed GicgEnv,seed 严格 `master_seed + game_idx` —
跨 paradigm 一致的 reproducibility 协议。

## 5. Retirement of `env_factory_legacy.py`

`training/core/env_factory_legacy.py`(2-arg `make_env_factory(cfg)`)曾是
AZ async hot path production,本 change 删除:

- AZ async_loop.py 切换到 canonical 3-arg signature
- `tools/run.py` 内 `_build_env_factory` inline helper 删除,改用
  canonical import
- `test_scenario_sampling.py` 切换 import
- `git rm training/core/env_factory_legacy.py`

替代路径:**全部** caller 改用
`from training.core.env_factory import make_env_factory`。`_legacy.py`
后缀命名禁止规则见 [`./paradigm-onboarding.md`](./paradigm-onboarding.md)
§7.6 + invariants.md #25 (PA-EF6)。

## 6. Cross-references

- 主 spec → [`./spec.md`](./spec.md)
- SHALL 锚定 → [`./invariants.md`](./invariants.md) #20-#25
- Paradigm 接入 SOP layout 引用 → [`./paradigm-onboarding.md`](./paradigm-onboarding.md) §3.1
- Anti-pattern(`_legacy.py` 后缀)→ [`./paradigm-onboarding.md`](./paradigm-onboarding.md) §7.6
- ScenarioConfig schema → `training/core/scenario.py` `ScenarioConfig`
- File layout 约定 → [`../openspec-policy/file-layout.md`](../openspec-policy/file-layout.md)
- Originating change → [`../../changes/archive/env-factory-unification/`](../../changes/archive/env-factory-unification/)

## 7. Status

- **Created**:2026-05-17(`env-factory-unification` archive merge)
- **Version**:0(初始,搬运 `env-factory-unification` spec delta A1
  + 6 SHALL invariants)
- **Expected revision triggers**:
  - 新 paradigm 引入 ObsConfig 之外的第 3 类 obs schema → §4 usage
    examples + SHALL #22/#23 可能扩展
  - `cfg.scenario` schema 扩展(如 multi-pool 支持)→ §2 canonical
    signature SHALL #24 (PA-EF5) 转发字段列表同步
  - GicgEnv 构造参数变更 → §2 + #24 转发字段同步
