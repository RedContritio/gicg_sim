# cfg-toml-restructure-paradigm-scoped — Architecture detail

> Detail extracted from top-level `design.md` at archive time (≤ 200 lines cap)。
> 内容:hybrid TOML structure 概念 + loader 改造 + schema 改动 + 5 Option
> pros/cons tradeoffs。

## 1. Architecture

### 1.1 Hybrid TOML structure

新 toml 顶层 schema:

```toml
[meta]
seed = 42
paradigm = "ppo"                 # dispatch selector (CC-308)
run_label = "ppo_default"
device = "cpu"

[pipeline]
mode = "serial"
num_actors = 1

[scenario]
team_0 = ["..."]

[shape]                          # 共享 obs schema (5 paradigm 共用 ObsShape schema)
n_counter_slots = 1648
n_hooks = 900
max_tokens_per_hook = 120
max_actions = 2048
d_model = 128
n_cross_layers = 2
dropout = 0.0

[eval]
schedule = "every_1000_steps"

[checkpoint]
save_every = 500

[paradigm.ppo]                   # paradigm-scoped 顶层 hparam
gamma = 0.99
clip_epsilon = 0.2

[paradigm.ppo.agent]             # paradigm-scoped sub-cfg, override [shape]
d_model = 256                    # PPO 默认 d_model=256, 覆盖共享 128

[paradigm.ppo.rollout]           # paradigm-scoped sub-cfg
n_games_per_iter = 32

[paradigm.az.mcts]               # 其它 paradigm 段 silent ignored (CC-304)
n_rollouts = 200
```

注意:
- **`[meta].paradigm`** 是 dispatch selector(CC-308),不引入 top-level
  `paradigm = "..."` scalar(避免 TOML scalar vs section 冲突)
- **`[shape]`** 顶层段可选;若存在,`[paradigm.<name>.agent]` 字段 override
  共享 `[shape]`(per-field dict merge,CC-303)
- **`[paradigm.<wrong_name>]`** 段 silent ignored(允许 reference cfg)

### 1.2 Loader 改造

新文件 `training/core/cfg/loader.py`(shared helper):

```python
"""Hybrid TOML structure loader helper.

Spec ref: config-schema/hybrid-toml-layout.md N6.1-N6.7.
"""

from __future__ import annotations
from typing import Any


def load_paradigm_cfg(toml_dict: dict, paradigm_name: str) -> dict:
    """Extract paradigm-scoped cfg from hybrid TOML root dict.

    Hybrid structure:
        - [shape]                        共享 obs schema (顶层)
        - [paradigm.<name>]              paradigm 顶层 hparam
        - [paradigm.<name>.X]            paradigm sub-cfg (X ∈ {agent, mcts, train, ...})

    Returns flat dict suitable for <X>ParadigmConfig.from_dict():
        - Top-level keys from [paradigm.<name>] (excluding sub-section dicts)
        - Sub-section keys (agent / mcts / ...) as nested dicts
        - [shape] merged into agent sub-dict if not overridden
    """
    pdict_root = toml_dict.get('paradigm', {})
    # Hard break: legacy flat structure detected (CC-301).
    if isinstance(pdict_root, dict):
        non_dict_keys = [k for k, v in pdict_root.items() if not isinstance(v, dict)]
        if non_dict_keys:
            raise ValueError(
                f'cfg: legacy flat [paradigm] structure detected (scalar keys {non_dict_keys}); '
                f'use hybrid [paradigm.{paradigm_name}.X] structure instead '
                f'(per cfg-toml-restructure-paradigm-scoped CC-301)'
            )

    paradigm_section = pdict_root.get(paradigm_name, {}) if isinstance(pdict_root, dict) else {}
    flat: dict = dict(paradigm_section)

    # Merge [shape] into 'agent' sub-dict (CC-305 + CC-303).
    shape = toml_dict.get('shape')
    if isinstance(shape, dict):
        existing_agent = flat.get('agent', {})
        merged_agent = {**shape, **existing_agent}
        flat['agent'] = merged_agent

    return flat
```

修改 `training/core/config/loader.py::load_cfg` — paradigm dispatch 改为:

```python
# (after validate_schema)
paradigm = resolved['meta']['paradigm']
validator = _load_paradigm_validator(paradigm)

# NEW: extract hybrid paradigm dict
from training.core.cfg.loader import load_paradigm_cfg
paradigm_flat = load_paradigm_cfg(resolved, paradigm)
validator(paradigm_flat)

return _build_dataclass(resolved, paradigm_flat)
```

### 1.3 Schema 改动

`training/core/config/schema.py::ALLOWED_TOP_LEVEL`:

```python
ALLOWED_TOP_LEVEL = {
    'meta', 'pipeline', 'eval', 'scenario',
    'paradigm', 'checkpoint',
    'shape',                      # NEW (cfg-toml-restructure-paradigm-scoped)
}
```

`[paradigm]` 的语义改为 "nested only"(无 scalar 字段);若 user 写
`[paradigm].lr=1e-3` flat scalar → loader raise hard break message。

## 2. Tradeoffs(5 Option pros/cons)

### 2.1 Option A — top-level `paradigm = "..."` selector(REJECTED per CC-308)

加 `paradigm = "ppo"` scalar 在 toml 顶层 + `[paradigm.ppo]` section。

- **Pros**:dispatch selector 在 toml 第一眼可见
- **Cons**:TOML 不允许 scalar 与 section 同名(`paradigm = "ppo"` +
  `[paradigm.X]` 冲突);需 rename selector 或 section,增加 confusion
- **Verdict**:REJECTED — `meta.paradigm` 已是 selector,不重复

### 2.2 Option B — meta.paradigm 仍是 selector(SELECTED, CC-308)

`meta.paradigm = "ppo"` 决定 dispatch;`[paradigm.ppo.X]` paradigm-scoped 段。

- **Pros**:无 toml 冲突;dispatch 语义无变化;最 minimal change
- **Cons**:dispatch selector 不在 toml 第一行,但在 [meta] 段第三行,仍可读
- **Verdict**:SELECTED

### 2.3 Option C — `[shape]` 必填(REJECTED per CC-305)

`[shape]` 顶层段每个 toml 都必须有。

- **Pros**:UI 一致,user 不会忘加
- **Cons**:smoke toml 不一定需要全量 obs schema(用 paradigm factory
  default 够了);加 8 个相同 `[shape]` 段是重复
- **Verdict**:REJECTED — `[shape]` 可选,缺则 factory default

### 2.4 Option D — `[paradigm.<wrong_name>]` raise(REJECTED per CC-304)

dispatch `paradigm = "ppo"`,toml 写 `[paradigm.az.mcts]` → raise unused。

- **Pros**:防 typo / 死段
- **Cons**:阻止 single toml 写多 paradigm 作 reference / ablation cfg
- **Verdict**:REJECTED — silent ignored,允许 multi-paradigm reference toml。
  可选 future `--strict` mode raise(out of scope)

### 2.5 Option E — Override 用 dataclass replace(REJECTED per CC-303)

`dataclasses.replace(shape_default, **paradigm_agent_dict)`。

- **Pros**:type-safe,字段错误立刻 raise
- **Cons**:loader 需 import ObsShape dataclass,与 from_dict 重复 validation;
  增加 cross-paradigm coupling
- **Verdict**:REJECTED — dict merge `{**shape, **agent}` 简洁,validation
  留给 paradigm.from_dict / build_shape_from_toml

### 2.6 Option F — Hard break vs migration tool(SELECTED hard break, CC-301)

旧 flat `[paradigm]` toml load 抛 error 或 auto-convert。

- **Pros (auto-convert)**:user 不需手改 toml
- **Cons (auto-convert)**:silent transform 违反 "严格契约,错误可见";
  debugging cfg 时 user 不知 effective cfg 长什么样
- **Verdict**:hard break — error message 指向 hybrid structure;
  `tools/cfg/migrate.py` 可作 future helper(out of scope)。
  本 change 直接 rewrite 10 toml,无 user-facing migration burden
