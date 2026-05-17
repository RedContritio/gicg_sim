# configs/

TOML 运行配置组织约定(P5-H 后子目录化,2026-05-16)。

## 子目录约定

| 子目录 | 含义 | 启用 |
|---|---|---|
| `active/` | 当前活跃实验 — 正在迭代 / 仍可能 rerun | 长期保留 |
| `smoke/` | smoke 测试 — pipeline 端到端验证、resume 机制测试、容器化烟雾 | 长期保留 |
| `shipped/` | 经过 verdict 的生产 baseline — testing / 对照参考 | 长期保留 |
| `_archived/<paradigm>_<month>/` | 已结案配置 — 按 paradigm + 月份归档 | 仅 git history reference,不 rerun |

`_archived/` 子目录里的 cfg **不再 rerun**,只作 git history 索引。若需复活,走 OpenSpec change un-archive 流程。

## 当前 `_archived/` 子目录

| 路径 | Paradigm | 月份范围 | 覆盖 |
|---|---|---|---|
| `_archived/az_apr/` | AlphaZero | 2026-04 | r001-r007 / r010 / `_tmp_r010` / `_tmp_r012` / s055-s069(stage 0-3 baselines + d4 mirror break) |
| `_archived/ppo_apr/` | PPO + BC warm-start | 2026-04 | s001-s002 backend bench / s005 d1 check / s008-s054 PPO 时代 + BC pretrain |
| `_archived/bc_apr/` | BC standalone | 2026-04 | r009 全套(data_gen + pretrain + eval ep0-ep6) |

CFR 时代(r008 prototype)无独立 cfg 落盘,因此 `_archived/cfr_apr/` 暂未创建。
DMC 历史(dmc_mp_smoke 等)在 P3.5 阶段已直接删除(见 docs/5_history/dmc_phase35_infra_impl/02_dmc_nan.md),无残留 cfg 需归档。

## Verdict 索引

每个 _archived 子目录的 paradigm verdict 见 `docs/5_history/`:

- AZ Stage 0-3 baselines → `docs/5_history/curriculum/stage[0-3].md`
- PPO Stage 0-3 完整诊断 → MEMORY.md `project_stage3_full_diagnosis`
- BC alone 评估 closure → MEMORY.md `project_bc_alone_evaluation`
- DMC Phase 3.5 → `docs/5_history/dmc_phase35_infra.md`

## 新增 cfg 该放哪里

| 场景 | 目标 |
|---|---|
| 新 RL run 启动迭代 | `active/<label>.toml` |
| 短 smoke / pipeline 验证 / resume 测试 | `smoke/<label>.toml` |
| 经过 verdict + 长期 reference baseline | `shipped/<label>.toml` |
| 实验结束 + 已写 verdict (postmortem / curriculum.md) | mv to `_archived/<paradigm>_<month>/` |

## 引用约定

代码 / docs 中引用 cfg 路径:

- Hardcoded 测试路径 — 包含子目录,如 `configs/smoke/dmc_stage3_smoke_v2.toml`
- 通配测试 — 用 `Path('configs').rglob('*.toml')` 递归 glob
- Tools entry 命令 — `tools/run.py configs/active/<label>.toml`(子目录显式)

`docs/5_history/runs_pre_redesign_2026_05_17.md`(post `core-network-generic-promotion`
2026-05-17 archive)内历史 run 记录的 cfg path 是历史 reference,不 mv path(保留
archive 视角)。Live run cfg 通过 `python -m tools.runs.show <run_id>` 查看。

## P5-H 之前的扁平结构

P5-H(2026-05-16)前所有 cfg 直接放 `configs/<label>.toml`,共 115 张。本次重组只 `git mv`,文件名不变,history 完整保留。
