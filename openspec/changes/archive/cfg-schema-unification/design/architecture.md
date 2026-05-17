# cfg-schema-unification — Architecture detail

> Detail extracted from top-level `design.md` at archive time (≤ 200 lines cap)。
> 内容:`ParadigmConfigBase` rewrite + factories + 4 paradigm config.py + configs/ toml
> + config_loader strictness。

## 1. Architecture

### 1.1 ParadigmConfigBase — drop `shape` field

```python
# training/core/cfg/base.py(rewrite)
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ParadigmConfigBase:
    """Base for paradigm-specific configs.

    Subclasses override:
    - `paradigm: str = '<name>'` — paradigm dispatch key
    - `version: str = '<X.Y.Z>'` — cfg schema version (bump on
      any field change to detect ckpt-cfg mismatch)

    Subclasses compose ObsShape via paradigm-local `agent` field
    (keeps caller `pcfg.agent.X` pattern, see CC-201 in DECISIONS).
    """

    version: str = '1.0.0'
    paradigm: str = ''
```

**Note**: original `ParadigmConfigBase` (post-Phase 1) had `shape: ObsShape` field but
this would force subclass to name the shape field `shape`. Existing paradigm runtime
code uses `pcfg.agent.X`(20+ access sites,见 `dmc/paradigm.py:58-64` 等)— renaming
all to `pcfg.shape.X` is large mechanical churn for zero functional gain. CC-201:
drop `shape` field from base,let subclass name shape field `agent`(type ObsShape)。

### 1.2 Factories — paradigm-specific ObsShape defaults

```python
# training/core/cfg/factories.py(new)
"""Paradigm-specific ObsShape factory functions.

Each factory returns ``ObsShape`` with paradigm 历史 production
default values (preserved from pre-unification AgentShapeCfg
defaults). 4 paradigm × 1 factory each — PPO not included
(PPO uses flat MLP, structural shape doesn't apply; see
cfg-schema-unification proposal § 4)。
"""

from training.core.cfg.shape import ObsShape

_BASE_SHAPE_FIELDS = dict(
    n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,  # 1832
    n_hooks=900,
    max_tokens_per_hook=120,
    max_actions=2048,
    dropout=0.0,
)


def make_az_default_shape() -> ObsShape:
    """AZ historical default — d_model=128 / n_cross_layers=2."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=128, n_cross_layers=2)


def make_bc_default_shape() -> ObsShape:
    """BC historical default — d_model=32 / n_cross_layers=1."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=32, n_cross_layers=1)


def make_cfr_default_shape() -> ObsShape:
    """CFR historical default — d_model=64 / n_cross_layers=2."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=64, n_cross_layers=2)


def make_dmc_default_shape() -> ObsShape:
    """DMC historical default — d_model=32 / n_cross_layers=1."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=32, n_cross_layers=1)
```

### 1.3 paradigm/config.py — inherit ParadigmConfigBase + AgentShapeCfg alias

```python
# training/paradigms/az/config.py(edit)
from training.core.cfg import ObsShape, ParadigmConfigBase
from training.core.cfg.factories import make_az_default_shape

# Backward-compat alias — preserves `from ... import AgentShapeCfg`
# pattern in test_az_paradigm_config_phase1.py + bc/network.py 等。
AgentShapeCfg = ObsShape


@dataclass(frozen=True)
class AZParadigmConfig(ParadigmConfigBase):
    paradigm: str = 'az'

    # ... existing top-level + sub-cfg fields unchanged ...

    agent: ObsShape = field(default_factory=make_az_default_shape)
    mcts: MCTSCfg = field(default_factory=MCTSCfg)
    train: TrainStepCfg = field(default_factory=TrainStepCfg)

    @classmethod
    def from_dict(cls, d: dict) -> 'AZParadigmConfig':
        # ... existing strict unknown-key + version/paradigm validation ...
```

`from_dict` 增加 strict validation:
- `version` field 不在 `d` → 沿用 default `'1.0.0'`(loader 允许缺失)
- `paradigm` 在 `d` 但与 cls.__dataclass_fields__['paradigm'].default 不一致 → raise
- `agent` 仍接受 dict,用 `ObsShape(**agent_d)` 构造(同语义,字段名相同)

### 1.4 4 paradigm 改动总览

| Paradigm | shape field name | factory | version | additional sub-cfg unchanged |
|---|---|---|---|---|
| AZ | `agent: ObsShape` | `make_az_default_shape` | '1.0.0' | mcts, train |
| BC | `agent: ObsShape` | `make_bc_default_shape` | '1.0.0' | (无 sub-cfg,直接 top-level) |
| CFR | `agent: ObsShape` (rename from CFRAgentShapeCfg) | `make_cfr_default_shape` | '1.0.0' | traversal |
| DMC | `agent: ObsShape` | `make_dmc_default_shape` | '1.0.0' | opponent_mix |

### 1.5 configs/<paradigm>/{default,smoke}.toml

每 paradigm 一个目录,2 toml(default + smoke)。每 toml 含:

```toml
[meta]
seed = 42
paradigm = "az"  # 必须与 [paradigm].paradigm 一致
run_label = "default"   # 或 "smoke"
device = "cpu"

[pipeline]
mode = "serial"

[scenario]
team_0 = ["凯亚"]
team_1 = ["凯亚"]
max_rounds = 15
deck_padding = { card = "碌碌无为", target_size = 15 }
pool = ["v_legacy", "test_basic"]

[paradigm]
version = "1.0.0"
paradigm = "az"
# ... paradigm-specific 字段 ...

[paradigm.agent]
n_counter_slots = 1832
n_hooks = 900
max_tokens_per_hook = 120
max_actions = 2048
d_model = 128   # smoke: 32
n_cross_layers = 2   # smoke: 1
dropout = 0.0
```

**default.toml**:用 paradigm 历史 production 默认 d_model(AZ=128 / BC=32 / CFR=64 / DMC=32),smoke d_model=32 统一。

**smoke.toml** 约束:
- d_model=32(per task hint #4)
- n_counter_slots ≥ 66(struct_readout 约束,我们用 1832 保持工程默认,不为 smoke 改)
- max_actions 小(128 足够 smoke)
- n_iterations / total_games / total_frames = 1
- max_steps = 30

### 1.6 config_loader strictness

4 paradigm `from_dict`:
1. **version validation**:`d.get('version', '1.0.0')` 默认 1.0.0;若 toml 显式 `version=...` 必须 ∈ `{'1.0.0'}`(将来扩展)
2. **paradigm validation**:`d.get('paradigm', '<x>')` 默认 paradigm 自身 dispatch key;若 toml 显式 `paradigm=...` 必须 == paradigm 自身 dispatch key
3. unknown key 仍 raise(CS4)

**Note**:`core/config/loader.py::_load_paradigm_validator` 已根据 `meta.paradigm` 路由到对应 `from_dict` — 若 `[paradigm].paradigm` 与 `meta.paradigm` mismatch,`from_dict` raise。

## 2. Tradeoffs

### 2.1 Option A — Rename `agent` field → `shape` field(REJECTED)

把 paradigm config `agent: AgentShapeCfg` 全改为 `shape: ObsShape`。

**Pros**:统一字段名,符合 task example。
**Cons**:20+ runtime 访问点(`dmc/paradigm.py:58-64` / `bc/paradigm.py:63-69` / `az/network.py`)用 `pcfg.agent.X` 需全部 rename;类似 paradigm test `pcfg.agent.d_model` 也要全改;
mechanical churn 30+ 文件,zero 功能收益。CC-201 决定:**REJECTED**,保持 `agent` 字段名 + ObsShape 类型。

### 2.2 Option B — Keep `agent` field name + ObsShape type(SELECTED)

`agent: ObsShape = field(default_factory=make_<x>_default_shape)`。

**Pros**:caller 代码 0 改动;type alias `AgentShapeCfg = ObsShape` 保 import 兼容;
spec invariant "ObsShape 单一 source of truth" 实现(同 dataclass type,paradigm 间共享)。
**Cons**:字段名 `agent` 与 type `ObsShape` 不同,稍 confusing(but 比 churn 30+ 文件好)。
**Verdict**:SELECTED。

### 2.3 Option C — drop `shape` from ParadigmConfigBase(SELECTED, paired with B)

`ParadigmConfigBase` 只留 `version` + `paradigm`。

**Pros**:Option B 选了 `agent` 字段名 — base 强行加 `shape` 字段会让 subclass 多一个未用字段;
drop `shape` 让 base 字段集与 subclass 实际字段集对应。
**Cons**:基类失去 "shape 是必填" 的契约表达。
**Verdict**:SELECTED。契约通过 subclass `agent: ObsShape` 表达;基类只表达 paradigm 通用元数据(version + paradigm dispatch key)。

### 2.4 Option D — 在 base 保 `shape` field 同时让 subclass override 为 `agent`(REJECTED)

`@dataclass` 不支持 subclass 用同名 field 改 type;若用不同名 `agent` field,基类 `shape` 仍存在 = dead 字段。
**Verdict**:REJECTED,违反"无 dead field"。

### 2.5 Option E — Version validation: enum vs free-form string(SELECTED enum)

`version ∈ {'1.0.0'}` enum check vs 任意 string。

**Pros (enum)**:typo(`'1.0'` vs `'1.0.0'`)立即 raise;future bump 是 explicit OpenSpec change。
**Cons (enum)**:每次 cfg schema 改 bump 需同步代码 + DECISIONS log。
**Verdict (enum)**:SELECTED — 符合 spec "严格契约,错误可见"。
