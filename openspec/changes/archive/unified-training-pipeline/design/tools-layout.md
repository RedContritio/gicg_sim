---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Tools Layout — 单入口 + 子目录分类

> 治理 `training-architecture/spec.md` SHALL #12(Single entry tool)落
> 地。完整规约由本 change 的 `../specs/tools-layout/spec.md` ship 进
> `openspec/specs/tools-layout/`。

## 1. 目标结构

```
tools/
├── run.py                      # 唯一训练入口
├── eval/                       # paradigm-agnostic eval(已 ship P0/WIP)
│   ├── arena.py
│   ├── matchup.py
│   ├── gauntlet.py
│   └── tournament.py
├── remote/                     # 远程操作(已 ship P0/WIP)
│   ├── send_matchup.py
│   ├── push_ckpt.py
│   └── pull_metrics.py
├── debug/                      # 原 diag_*.py
│   ├── diag_action_mask.py
│   ├── diag_value_pred.py
│   └── diag_inspect_ckpt.py
├── probe/                      # 原 probe_*.py
│   ├── probe_attention.py
│   └── probe_obs_invariance.py
├── profile/                    # 原 profile_*.py
│   ├── profile_actor.py
│   └── profile_inference.py
├── bench/                      # 原 bench_*.py
│   ├── bench_step.py
│   └── bench_engine.py
├── replay/                     # replay 工具
│   ├── dump.py
│   └── check.py
├── dataset/                    # BC dataset gen / inspect
│   ├── gen_bc_dataset.py
│   └── inspect_bc_dataset.py
├── cards/                      # 已组织 (P0+P1)
│   ├── strip_card_yaml.py
│   └── ...
└── _meta/                      # 项目维护(已 ship P0-T4/T5)
    ├── check_line_limits.py
    └── check_openspec_indices.py
```

## 2. 单入口 `tools/run.py`

```python
# Usage:
#   python -m tools.run cfg.toml
#   python -m tools.run cfg.toml --paradigm.lr=1e-5
#   python -m tools.run cfg.toml --override paradigm.buffer_cap=200_000

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cfg_path", type=Path)
    parser.add_argument("--override", nargs="+", default=[])
    args = parser.parse_args()

    cfg_dict = load_toml_with_extends(args.cfg_path)
    cfg_dict = apply_overrides(cfg_dict, args.override)
    cfg_dict = resolve_inheritance(cfg_dict)
    validate_schema(cfg_dict)
    cfg = build_training_config(cfg_dict)

    print_run_banner(cfg)         # cfg hash / artifacts dir / paradigm
    from training.core.pipeline import run_pipeline
    run_pipeline(cfg)
```

替代当前的:
- `tools/launch_az.py` / `launch_config.py` / `run_cfr.py` / `run_dmc.py` /
  `ppo_launch.py`(全部删除)
- `tools.run_dmc <cfg>` → `python -m tools.run <cfg>`(cfg.meta.paradigm
  决定 dispatch)

## 3. paradigm-agnostic 原则

每子目录(eval / remote / debug / probe / profile / bench / replay / dataset)
SHALL 完全 paradigm-agnostic:
- 工具读 ckpt path(标准 `ckpt.pt` 格式)
- 工具读 cfg.toml(标准 schema)
- 工具不 import `training.paradigms.<name>`(若 paradigm-specific 操作
  需要,该工具 belongs to `training/paradigms/<name>/tools/`,**不**在
  `tools/`)

例外:`tools/_meta/`(项目维护工具,不 import training)+ `tools/cards/`
(DSL 数据预处理,不依赖 training)。

## 4. 当前 paradigm-specific 工具去向

| 当前位置 | 操作类型 | P5 去向 |
|---|---|---|
| `tools/launch_az.py` | 入口 | DELETE,用 `tools/run.py` |
| `tools/launch_config.py` | 入口 | DELETE,用 `tools/run.py` |
| `tools/run_cfr.py` | 入口 | DELETE,用 `tools/run.py` |
| `tools/ppo_launch.py` | 入口 | DELETE,用 `tools/run.py` |
| `tools/gen_bc_dataset_az.py` | dataset | MOVE `tools/dataset/gen_bc_dataset.py` |
| `tools/az_arena.py` | eval | MOVE `tools/eval/arena.py`(paradigm-agnostic) |
| `tools/diag_*.py` | debug | MOVE `tools/debug/` |
| `tools/probe_*.py` | probe | MOVE `tools/probe/` |
| `tools/profile_*.py` | profile | MOVE `tools/profile/` |
| `tools/bench_*.py` | bench | MOVE `tools/bench/` |
| `tools/dump_replay.py` | replay | MOVE `tools/replay/dump.py` |

D5 决策:**不直接删,合并分类**。原文件 git mv 进新位置 + 适配 paradigm-
agnostic interface(`--ckpt` 而非 `--az-ckpt`)。

## 5. paradigm-specific tools(若需要)

每 paradigm 自己的诊断工具进 `training/paradigms/<name>/tools/`:

```
training/paradigms/az/
├── paradigm.py
├── tools/
│   ├── mcts_inspect.py         # AZ-specific tree visualization
│   └── temperature_sweep.py    # AZ-specific
```

调用方式:`python -m training.paradigms.az.tools.mcts_inspect <ckpt>`。

## 6. Configs 重组(P5 副作用)

```
configs/
├── _base/                       # extends 基础 cfg
│   ├── env_v_phase2.toml
│   └── meta_seed42.toml
├── dmc/
│   ├── v_phase2_stage3.toml
│   └── v_phase2_smoke.toml
├── az/
│   ├── c1v7_pool0.toml
│   └── ...
├── ppo/
│   └── archive_repro.toml
├── cfr/
│   └── archive_repro.toml
└── bc/
    └── r009_warmstart.toml
```

替代当前 `configs/*.toml` flat layout(15+ 文件混在根)。

## 7. SHALL invariants(by spec delta)

详 `../specs/tools-layout/spec.md`:
- T1:`tools/run.py` 是 paradigm-agnostic 训练唯一入口
- T2:`tools/` 顶层文件 SHALL 是 `run.py` + 1 README.md;其余进子目录
- T3:子目录命名固定:eval / remote / debug / probe / profile / bench /
  replay / dataset / cards / _meta
- T4:paradigm-specific 工具进 `training/paradigms/<name>/tools/`
- T5:每子目录 README.md 描述 scope + 工具列表
- T6:工具 entry SHALL 用 `python -m` 形式(详 CLAUDE.md)

## 8. Cross-references

- Spec delta → [`../specs/tools-layout/spec.md`](../specs/tools-layout/spec.md)
- 当前 cwd 约定 → memory project_cwd_convention
- 主 spec → [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md) SHALL #12
- Migration plan → [`./migrations.md`](./migrations.md)
