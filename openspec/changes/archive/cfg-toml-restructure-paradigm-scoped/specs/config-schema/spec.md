---
last_updated: 2026-05-17
status: DELTA
schema_version: 0
change_id: cfg-toml-restructure-paradigm-scoped
delta_type: MODIFY+ADD
capability: config-schema
---

# config-schema spec delta — cfg-toml-restructure-paradigm-scoped

> Delta on top of `openspec/specs/config-schema/spec.md`(LIVE)。
> Merge targets:
> - § MODIFY invariant N5(configs/ layout)— 改为 hybrid TOML structure 描述
> - § ADD new section "## 8. Hybrid TOML structure(paradigm-scoped sections)"
> Archive-time merge per opensec-policy SOP。

## MODIFY § 7 N5 — configs/<paradigm>/{default,smoke}.toml(hybrid)

**N5.1** `configs/` SHALL contain per-paradigm subdirectory for **all 5** paradigm
(AZ / BC / CFR / DMC / PPO),each with `default.toml` + `smoke.toml`:
- `configs/az/{default,smoke}.toml`
- `configs/bc/{default,smoke}.toml`
- `configs/cfr/{default,smoke}.toml`
- `configs/dmc/{default,smoke}.toml`
- `configs/ppo/{default,smoke}.toml`  *(added by cfg-toml-restructure)*

**N5.2** Each `default.toml` SHALL declare paradigm-specific production defaults
(参考 `_archived/{shipped,active}/`)。

**N5.3** Each `smoke.toml` SHALL declare minimum viable cfg(d_model=32 /
n_iter=1 / total_games small / max_steps=30)足够 smoke pipeline alive verify。

**N5.4** Each toml `[meta]` section SHALL contain `paradigm` key matching the
dispatch selector(loader looks up `meta.paradigm` to route to paradigm
validator)。

**N5.5** PPO `configs/ppo/{default,smoke}.toml` SHALL now exist (was deferred in
cfg-schema-unification);per `cfg-toml-restructure-paradigm-scoped` CC-309 PPO toml
uses hybrid `[shape]` + `[paradigm.ppo.agent]` override structure. PPO config
dataclass type remains `PPOAgentShapeCfg` (not yet `ObsShape`);DRY through toml
structure only。

## ADD § 8. Hybrid TOML structure(paradigm-scoped sections)

### N6. Hybrid TOML layout — `[shape]` shared + `[paradigm.<name>.X]` scoped

**N6.1** Each cfg toml `[paradigm]` block SHALL contain ONLY nested
sub-sections of the form `[paradigm.<paradigm_name>.<sub>]` or
`[paradigm.<paradigm_name>]` — NO scalar key directly under `[paradigm]`
(per `cfg-toml-restructure-paradigm-scoped` CC-301 hard break)。
Legacy flat `[paradigm].lr = ...` etc. → loader SHALL raise
`'legacy flat [paradigm] structure detected'`。

**N6.2** Paradigm dispatch SHALL use `meta.paradigm` selector(per CC-308)。
Loader SHALL extract `[paradigm.<meta_paradigm>]` section (top-level
paradigm hparam) + `[paradigm.<meta_paradigm>.X]` sub-sections (agent /
mcts / train / rollout / ...) into a flat dict equivalent to the
legacy `[paradigm]` shape, then dispatch to `<X>ParadigmConfig.from_dict()`。

**N6.3** Non-dispatched paradigm sections SHALL be silently ignored
(per CC-304):toml MAY contain `[paradigm.az.X]` + `[paradigm.ppo.X]`
simultaneously;dispatch with `meta.paradigm = "ppo"` uses only ppo
sections, az sections ignored without raise. This enables single toml
multi-paradigm reference cfgs。

**N6.4** `[shape]` top-level section is OPTIONAL(per CC-305):
- If present, SHALL be a dict of ObsShape fields(subset OK)
- Loader SHALL merge `[shape]` into the paradigm `agent` sub-dict as
  base, with `[paradigm.<name>.agent]` values overriding `[shape]`
  per-field (dict merge `{**shape, **agent}` per CC-303)
- If missing, paradigm uses `make_<X>_default_shape()` factory default
  (per cfg-schema-unification N1.2)

**N6.5** `load_paradigm_cfg(toml_dict, paradigm_name) -> dict` helper SHALL
be implemented at `training/core/cfg/loader.py`(per CC-306)and called
by `core/config/loader.py::load_cfg` before paradigm dispatch validator。
The helper SHALL be shared across all paradigms (no paradigm-local
re-implementation)。

**N6.6** Top-level cfg keys SHALL include `'shape'` in the
`ALLOWED_TOP_LEVEL` set(per `core/config/schema.py`)。Other allowed
top-level segments unchanged from N5: `meta` / `pipeline` / `eval` /
`scenario` / `paradigm` / `checkpoint` / `shape`。

**N6.7** Example hybrid toml(non-normative):

```toml
[meta]
seed = 42
paradigm = "ppo"
run_label = "ppo_default"
device = "cpu"

[pipeline]
mode = "serial"

[scenario]
team_0 = ["..."]

[shape]                          # 共享 obs schema (N6.4)
d_model = 128
n_cross_layers = 2

[checkpoint]
save_every = 500

[paradigm.ppo]                   # paradigm-scoped 顶层 hparam (N6.2)
gamma = 0.99
clip_epsilon = 0.2

[paradigm.ppo.agent]             # paradigm-scoped sub-cfg, override [shape]
d_model = 256                    # CC-302 override 显示 (effective: 256)

[paradigm.ppo.rollout]
n_games_per_iter = 32

[paradigm.az.mcts]               # 其它 paradigm 段 ignored (N6.3)
n_rollouts = 200
```

## Cross-references

- Originating change → `openspec/changes/cfg-toml-restructure-paradigm-scoped/proposal.md`
- DECISIONS log → `openspec/changes/cfg-toml-restructure-paradigm-scoped/DECISIONS.md`
  - CC-301: hard break, no legacy flat compat
  - CC-302: PPO toml [shape]=128 + [paradigm.ppo.agent]=256 override
  - CC-303: dict merge (not dataclass replace)
  - CC-304: non-dispatched paradigm sections silent ignored
  - CC-305: [shape] optional, factory default fallback
  - CC-306: load_paradigm_cfg shared helper in core/cfg/loader.py
  - CC-307: spec delta merge deferred to archive workflow
  - CC-308: dispatch selector remains meta.paradigm (no top-level scalar)
  - CC-309: PPO toml接入 hybrid structure (dataclass unchanged)
- Predecessor change(deferred decisions):
  `openspec/changes/archive/core-network-generic-promotion/DECISIONS.md` D-501
