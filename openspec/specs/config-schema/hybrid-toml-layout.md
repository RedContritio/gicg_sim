---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: config-schema
subtopic: hybrid-toml-layout
---

# Config Schema — Hybrid TOML Layout(paradigm-scoped sections)

> 本 subtopic 落地 `config-schema` § 8 N6(hybrid TOML layout)7 SHALL:
> `[shape]` global 共享段 + `[paradigm.<name>.<sub>]` paradigm-scoped nested
> 段,dispatch via `meta.paradigm`;非 dispatched paradigm section silent
> ignored,允许 single toml 写多 paradigm 作 reference / cross-compare /
> ablation cfg。
>
> 适用范围:5 paradigm(AZ / BC / CFR / DMC / PPO)。PPO 自
> `ppo-structural-backbone-migration` archive 2026-05-17 起 toml 层接入,
> 与其它 4 paradigm 完全对称。

## N6.1 paradigm block nested structure(SHALL)

每个 cfg toml `[paradigm]` block SHALL 只包含 `[paradigm.<paradigm_name>]`
顶层 或 `[paradigm.<paradigm_name>.<sub>]` nested sub-section,NO scalar
key 直接 under `[paradigm]`(per `cfg-toml-restructure-paradigm-scoped`
CC-301 hard break)。

Legacy flat 形态:

```toml
[paradigm]                       # 旧 — REJECTED
lr = 1e-3
batch_size = 32
[paradigm.agent]
d_model = 128
```

旧 flat `[paradigm].lr = ...` 等 scalar key under `[paradigm]` 时,
loader SHALL raise `'cfg: legacy flat [paradigm] structure detected
(scalar keys [...]); use hybrid [paradigm.<name>.X] structure instead
(per cfg-toml-restructure-paradigm-scoped CC-301)'`。

新 hybrid 形态:

```toml
[paradigm.az]                    # paradigm-scoped 顶层 hparam
gamma = 0.99

[paradigm.az.agent]              # paradigm-scoped sub-cfg
d_model = 128

[paradigm.az.mcts]               # 另一 sub-cfg
n_rollouts = 200
```

## N6.2 dispatch via meta.paradigm

Paradigm dispatch SHALL use `meta.paradigm` selector(per CC-308)。
TOML 不允许 scalar `paradigm = "ppo"` 与 section `[paradigm.X]` 同 path
共存(语法冲突),故 dispatch 仍走 `[meta].paradigm = "..."`(unchanged
from current loader)。

Loader SHALL:
1. 读 `meta.paradigm` 拿到 `paradigm_name`
2. 抽取 `[paradigm.<paradigm_name>]`(顶层 paradigm hparam)
3. 抽取 `[paradigm.<paradigm_name>.<sub>]` sub-sections(agent / mcts /
   train / rollout / ...)成 flat dict,等价于 legacy `[paradigm]` shape
4. Dispatch 到 `<X>ParadigmConfig.from_dict(flat_dict)`

## N6.3 non-dispatched paradigm silent ignored

Dispatch 时,toml 中 `[paradigm.<other_name>.X]` 段 SHALL silent ignored
(不 raise / 不 warn,per CC-304):

```toml
[meta]
paradigm = "ppo"                 # dispatch selects ppo

[paradigm.ppo.agent]             # USED
d_model = 256

[paradigm.az.mcts]               # IGNORED (silent, no raise)
n_rollouts = 200

[paradigm.cfr.train]             # IGNORED (silent, no raise)
lr = 1e-4
```

这允许 single toml 写多 paradigm cfg 作 reference / cross-compare /
ablation。Future `--strict` mode 可加 raise on unused(out of scope for
本 invariant)。

## N6.4 [shape] optional default

`[shape]` 顶层段 SHALL be OPTIONAL(per CC-305):

- 若 present,SHALL be a dict of `ObsShape` fields(subset OK)
- Loader SHALL merge `[shape]` 进 paradigm `agent` sub-dict 作 base,
  `[paradigm.<name>.agent]` 字段 override `[shape]` per-field(dict merge
  `{**shape, **agent}` per CC-303,简洁;dataclass replace 会 import
  ObsShape 引入 coupling — REJECTED per Option E)
- 若 missing,paradigm 用 `make_<X>_default_shape()` factory default
  (per obs-shape-unification N1.2)

Example override:

```toml
[shape]
d_model = 128                    # 共享 base

[paradigm.ppo.agent]
d_model = 256                    # PPO override → effective 256
```

强制 `[shape]` 会让所有 toml 都重复写相同 7 字段(纯噪声),smoke toml
不需写全量 obs schema — factory default 足以让 smoke pipeline alive。

## N6.5 load_paradigm_cfg helper

`load_paradigm_cfg(toml_dict: dict, paradigm_name: str) -> dict` helper
SHALL 实施在 `training/core/cfg/loader.py`(per CC-306),由
`training/core/config/loader.py::load_cfg` 在 paradigm dispatch validator
之前调用。

Helper SHALL 是 paradigm-agnostic shared(5 paradigm 共用):

- 5 paradigm helper 行为完全相同(extract `[paradigm.<name>]` + merge
  `[shape]`)— 重复 5 次违反 DRY
- `core/cfg/` 已是 paradigm-agnostic cfg primitives 集合点(`ObsShape` +
  `ParadigmConfigBase` + factories),loader 同性质
- 入口仍是 `core/config/loader.py::load_cfg`(unified pipeline loader);
  `core/cfg/loader.py` 是 sub-step helper

Future 若有 paradigm-specific hybrid quirk,可在 paradigm
`config_loader.py` 包装(out of scope for 本 invariant)。

## N6.6 ALLOWED_TOP_LEVEL include 'shape'

`training/core/config/schema.py::ALLOWED_TOP_LEVEL` set SHALL include
`'shape'`(顶层共享段)。

合法顶层段(本 invariant 之后):

```python
ALLOWED_TOP_LEVEL = {
    'meta',         # paradigm / seed / device / experiment_tag / run_label
    'pipeline',     # mode / num_actors / learner / inference
    'eval',         # n_workers / inference / schedule
    'scenario',     # team / pool / max_rounds
    'paradigm',     # nested [paradigm.<name>.X] only (N6.1)
    'checkpoint',   # save_every / artifacts_root
    'shape',        # 共享 obs schema (N6.4) — added by cfg-toml-restructure
}
```

R8 placement:`[paradigm.<wrong_name>.X]` 段 silent ignored 不算 schema
violation(per N6.3);unknown top-level 段(不在 set 内)仍 raise per
CS4.1。

## N6.7 详细 toml 例子(含 PPO override)

非 normative 示例(完整 hybrid toml):

```toml
[meta]
seed = 42
paradigm = "ppo"                 # dispatch selector (N6.2)
experiment_tag = "ppo_default"
run_label = "ppo_default"
device = "cpu"

[pipeline]
mode = "serial"
num_actors = 1

[scenario]
team_0 = ["..."]

[shape]                          # 共享 obs schema (N6.4) — 可选
n_counter_slots = 1648
n_hooks = 900
max_tokens_per_hook = 120
max_actions = 2048
d_model = 128
n_cross_layers = 2
dropout = 0.0

[checkpoint]
save_every = 500

[paradigm.ppo]                   # paradigm-scoped 顶层 hparam (N6.1)
gamma = 0.99
clip_epsilon = 0.2

[paradigm.ppo.agent]             # paradigm-scoped sub-cfg, override [shape]
d_model = 256                    # CC-302 override 显示 (effective: 256)

[paradigm.ppo.rollout]           # paradigm-scoped sub-cfg
n_games_per_iter = 32

[paradigm.az.mcts]               # 其它 paradigm 段 silent ignored (N6.3)
n_rollouts = 200
```

Loader 看到 `meta.paradigm = "ppo"` 后,提取 `[paradigm.ppo]` +
`[paradigm.ppo.agent]` + `[paradigm.ppo.rollout]`,merge `[shape]` 进
agent(`d_model` 被 agent override 成 256),`[paradigm.az.mcts]` 整段
ignored,最终 flat dict 喂 `PPOParadigmConfig.from_dict()`。

## Cross-references

- Originating change → `openspec/changes/archive/cfg-toml-restructure-paradigm-scoped/proposal.md`
- DECISIONS log → `openspec/changes/archive/cfg-toml-restructure-paradigm-scoped/DECISIONS.md`
  - CC-301: hard break, no legacy flat compat
  - CC-302: PPO toml [shape]=128 + [paradigm.ppo.agent]=256 override
  - CC-303: dict merge (not dataclass replace)
  - CC-304: non-dispatched paradigm sections silent ignored
  - CC-305: [shape] optional, factory default fallback
  - CC-306: load_paradigm_cfg shared helper in core/cfg/loader.py
  - CC-307: spec delta merge deferred to archive workflow
  - CC-308: dispatch selector remains meta.paradigm (no top-level scalar)
  - CC-309: PPO toml 接入 hybrid structure (dataclass unchanged)
- Predecessor change(deferred decisions)→
  `openspec/changes/archive/core-network-generic-promotion/DECISIONS.md` D-501
- Parent SHALL summary in main spec.md → § 8
- Implementation:
  - `training/core/cfg/loader.py::load_paradigm_cfg`(N6.5 helper)
  - `training/core/config/loader.py::load_cfg`(invokes helper)
  - `training/core/config/schema.py::ALLOWED_TOP_LEVEL`(N6.6)
