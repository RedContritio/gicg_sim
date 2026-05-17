---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfg-toml-restructure-paradigm-scoped
---

# Proposal — cfg-toml-restructure-paradigm-scoped

## 1. Why

Per user 2026-05-17 决策(D-501 in `core-network-generic-promotion` DECISIONS),
当前 cfg toml 用 flat `[paradigm]` 段命名:

```toml
paradigm = "az"                # top-level dispatch selector
[paradigm]                     # ambiguous — section name 无 paradigm context
version = "1.0.0"
paradigm = "az"
lr = 1e-3
[paradigm.agent]               # paradigm sub-section
d_model = 128
[paradigm.mcts]
n_rollouts = 200
```

Pain points:
- Section `[paradigm]` 无 paradigm 名字,阅读时必须 cross-ref top-level `paradigm = "..."`
- 同一 toml 不能存共存多 paradigm cfg(e.g. AZ + PPO compare),复用度差
- `[paradigm.agent]` 表面像 paradigm 通用字段,实际是 paradigm-local — 名实不副

Hybrid 形态(D-501 决策)统一改成:

```toml
paradigm = "ppo"                       # dispatch selector (top-level)

[shape]                                # 共享段 (5 paradigm 同 obs schema)
n_counter_slots = 1832
d_model = 128

[paradigm.ppo]                         # paradigm-scoped (顶层 paradigm hparam)
gamma = 0.99

[paradigm.ppo.agent]                   # paradigm-scoped sub-cfg, 可 override [shape]
d_model = 256                          # PPO 默认 d_model=256, override 共享 128

[paradigm.az.mcts]                     # 同 toml 可写 reference cfg, dispatch 不选时 ignored
n_rollouts = 200
```

Pre-requisite ship 完成:
- `cfg-schema-unification`(`ad0e54a/ac21d88/e81f67d`)— 4 paradigm cfg dataclass 已用 `ObsShape + ParadigmConfigBase`
- `ppo-structural-backbone-migration`(`2bad91d/a512ee1/97a9609/d30f335`)— PPO 切到 generic backbone,字段对齐

## 2. What

**5 bullets**:

1. 新 `training/core/cfg/loader.py` — shared hybrid TOML merge helper `load_paradigm_cfg(toml_dict, paradigm_name) -> dict` 提取 `[paradigm.<name>]`(顶层 hparam)+ `[paradigm.<name>.X]`(sub-cfg)+ merge 共享 `[shape]` → 喂给 `<X>ParadigmConfig.from_dict()`
2. 修改 `training/core/config/loader.py::load_cfg` — 在 paradigm dispatch 前先 call `load_paradigm_cfg(raw, paradigm)` 把 hybrid TOML 改成 flat dict
3. 修改 `training/core/config/schema.py::ALLOWED_TOP_LEVEL` — `+'shape'`(顶层共享段);R8 placement: `[paradigm.<wrong_name>]` 段 silent ignored(per CC-304)
4. 10 toml restructure(hybrid 形态):
   - `configs/{az,bc,cfr,dmc}/{default,smoke}.toml` — 8 文件改 hybrid
   - `configs/ppo/{default,smoke}.toml` — 2 新文件(per #4 后 PPO 已 generic backbone)
5. 4 test 文件:`test_cfg_toml_hybrid.py`(loader + hybrid semantics + override + dispatch + ignored)+ 更新已有 paradigm config_loader smoke test

## 3. Affected specs

- `config-schema/spec.md` § MODIFY invariant N5(configs/ layout)+ ADD invariant N6(hybrid TOML structure)
- 主 spec.md `ALLOWED_TOP_LEVEL` 列表 + R8 ignored paradigm 段说明
- 无 paradigm-spec 修改

## 4. Out of scope

- **不动** PPO backbone code(已 ship 在 #4);只动 toml structure + loader
- **不动** 其它 paradigm 算法代码(`paradigm.py` / `collector.py` / `loss.py` 等)
- **不动** `configs/_archived/pre_redesign_2026_05_17/`(历史保留)
- **不增** override semantics 之外的新 cfg 段;`[shape]` / `[scenario]` / `[eval]` / `[checkpoint]` / `[meta]` 仍是 current 5 顶层段集合
- **不改** paradigm cfg dataclass 字段集(`AZParadigmConfig` 等 unchanged;只是 from_dict 的 input dict 形态变了)
- **不改** override CLI semantics(`--override key.path=value` 仍按 dot path,但 path 现在 reference hybrid 结构)
- **不删** 旧 flat toml 兼容:hard break,旧 toml load 抛清晰 error 指向新结构(per CC-301)

## 5. Decision summary(详 DECISIONS.md)

- **[CC-301] Hard break**:旧 flat `[paradigm]` toml load 抛清晰 error,不留兼容
- **[CC-302] PPO `[shape]` d_model=128 + `[paradigm.ppo.agent]` override 256**:显示 override 能力
- **[CC-303] Override 实现 = dict merge**:loader 层处理,paradigm dataclass 不感知 merge
- **[CC-304] `[paradigm.<wrong_name>]` silent ignored**:允许 single toml 写多 paradigm 作 reference
- **[CC-305] `[shape]` 顶层段可选**:若缺,paradigm 用 `make_<X>_default_shape()` factory 默认;存在则 paradigm 段 agent merge override
- **[CC-306] Loader 位置 = `core/cfg/loader.py` shared helper**:5 paradigm 共用
- **[CC-307] Spec delta merge 推迟到 archive workflow**:与 cfg-schema-unification CC-209 / core-network-generic-promotion D-401 同
- **Effort**:~250 LOC(loader 80 + 10 toml restructure ~400 + 1 test 150)
