---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../tasks.md
---

# Phase 5 — git mv 物理 paradigms/ + tools 分类 + configs 重组

> P3-P4 验证逻辑层 + 单 paradigm 通过新管线后,本 phase 一次性物理 mv:
> `training/{az,cfr,dmc,ppo}/` → `training/paradigms/`,删 `training/framework/`,
> tools/ 子目录化,configs/ 子目录化。一次大 commit + import 全 grep 验证。

## 1. 总 LOC 估 / Wall

- **LOC 估**:~10000(主要 git mv,实际新增/删除 LOC < 1500)
- **Wall 估**:~1 week(主要 import 重写 + 测试)
- **Smoke 门槛**:0 regression(全 pytest pass + 全 cfg validate + 全
  paradigm smoke pass + r009 ckpt acc 重现)

## 2. P5-T1 创建 paradigms/ 子目录 + git mv

- [x] **P5-T1.1**:`mkdir -p training/paradigms/{az,dmc,cfr,ppo,bc}`
- [x] **P5-T1.2**:`git mv training/az training/paradigms/az/_legacy`(暂留
  legacy 子目录,内容逐步抽出到 P4 ship 的 paradigm files)
- [x] **P5-T1.3**:同 P5-T1.2 for dmc / cfr / ppo
- [x] **P5-T1.4**:`paradigms/<name>/_legacy/` 内容逐文件 review:抽出 keep
  → `paradigms/<name>/`,删 obsolete
- [x] **P5-T1.5**:删 `paradigms/<name>/_legacy/` 空目录
- [x] **P5-T1.6**:`training/paradigms/__init__.py` paradigm registry(name
  → class lookup)(~50 LOC)

依赖:P4 ship(P4 已写 `paradigms/<name>/paradigm.py` 等接入文件)

## 3. P5-T2 删除 framework/

- [x] **P5-T2.1**:`grep -rn "from training.framework" .` 全列(预期 P3
  ship 后剩余 ≤ 20 处)
- [x] **P5-T2.2**:逐 import 改为 `from training.core.*`(adapter 化)
- [x] **P5-T2.3**:再 grep,0 残留
- [x] **P5-T2.4**:`git rm -r training/framework/`
- [x] **P5-T2.5**:加 import-linter 配置 forbid `training.framework`(~30 LOC)

依赖:P5-T1.6

## 4. P5-T3 tools/ 子目录化

- [x] **P5-T3.1**:`mkdir tools/{eval,remote,debug,probe,profile,bench,replay,dataset}`
- [x] **P5-T3.2**:`git mv tools/diag_*.py tools/debug/`(rename `diag_` →
  纯 name)
- [x] **P5-T3.3**:`git mv tools/probe_*.py tools/probe/`
- [x] **P5-T3.4**:`git mv tools/profile_*.py tools/profile/`
- [x] **P5-T3.5**:`git mv tools/bench_*.py tools/bench/`
- [x] **P5-T3.6**:`git mv tools/dump_replay.py tools/replay/dump.py`
- [x] **P5-T3.7**:`git mv tools/check_replay.py tools/replay/check.py`
- [x] **P5-T3.8**:`git mv tools/gen_bc_dataset_az.py tools/dataset/gen_bc_dataset.py`
- [x] **P5-T3.9**:`git mv tools/inspect_bc_dataset.py tools/dataset/inspect.py`
- [x] **P5-T3.10**:`git mv tools/az_arena.py tools/eval/arena.py`(adapter
  化:`--az-ckpt` → `--ckpt`)
- [x] **P5-T3.11**:`git mv tools/send_matchup.py tools/remote/send_matchup.py`
- [x] **P5-T3.12**:`git mv tools/push_ckpt.py tools/remote/push_ckpt.py`(若
  exists)
- [x] **P5-T3.13**:删 `tools/launch_az.py` / `launch_config.py` / `run_cfr.py` /
  `ppo_launch.py` / `run_dmc.py`(被 `tools/run.py` 取代)
- [x] **P5-T3.14**:每子目录加 `README.md` 说明 scope + 工具列表(~10 LOC each)
- [x] **P5-T3.15**:全 `python -m tools.<sub>.<name>` 命令重写到文档 / scripts

依赖:P4 ship

## 5. P5-T4 configs/ 子目录化

- [x] **P5-T4.1**:`mkdir configs/{_base,dmc,az,cfr,ppo,bc}`
- [x] **P5-T4.2**:`git mv configs/<dmc-related>.toml configs/dmc/`
- [x] **P5-T4.3**:同 P5-T4.2 for az / cfr / ppo / bc
- [x] **P5-T4.4**:抽 `configs/_base/env_v_phase2.toml` + `configs/_base/meta_seed42.toml`
  (~50 LOC each)
- [x] **P5-T4.5**:各 cfg 加 `extends = "configs/_base/<base>.toml"`
- [x] **P5-T4.6**:`configs/README.md` 说明子目录 + extends 规则(~50 LOC)

依赖:P3-T2 ship(extends resolver)

## 6. P5-T5 ckpt path 在文档 / scripts 更新

- [x] **P5-T5.1**:grep `tools.launch_` / `tools.run_dmc` / `tools.launch_config`
  在 docs/ + memory/ 全替换为 `tools.run`
- [x] **P5-T5.2**:CLAUDE.md 的 "Running Python scripts" section 更新示例
  命令
- [x] **P5-T5.3**:docker compose `tools/dc.sh` train command 更新

依赖:P5-T3

## 7. P5-T6 全 pytest + 全 cfg validate

- [x] **P5-T6.1**:`.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/`
  全 pass
- [x] **P5-T6.2**:全 configs/**/*.toml `python -m tools.run --dry-run` pass
- [x] **P5-T6.3**:5 paradigm 各跑 smoke(serial mode 短 wall)pass
- [x] **P5-T6.4**:r009 ckpt acc 重现(必 ± 0.005)
- [x] **P5-T6.5**:ruff format + gofmt + check_line_limits + check_openspec_indices
  全 pass
- [x] **P5-T6.6**:grep `from training.framework` 在全 repo 0 残留
- [x] **P5-T6.7**:grep `tools/launch_` / `tools/run_dmc` 等 0 残留 in
  docs/scripts

依赖:P5-T1 to P5-T5

## 8. P5-T7 文档同步

- [x] **P5-T7.1**:`docs/0_status/README.md` 更新当前 phase
- [x] **P5-T7.2**:`CLAUDE.md` 顶部 "Repo Layout" 段更新(`training/{framework,az,...}`
  → `training/{core,paradigms/<name>}`)
- [x] **P5-T7.3**:memory `project_training_layout` 更新 entry(注:user
  保留 historical entry,加新 entry)
- [x] **P5-T7.4**:`openspec/project.md` 更新(若有 training-stack 提及)

依赖:P5-T6 pass

## 9. P5 ship 门槛

P5-T1-T7 全 done + 0 regression → P5 ship。
进入 P6(archive)。

## 10. P5.5 / P5.6 conditional Go 化(独立 follow-up changes)

- **P5.5 G2**:cgo step + encode 合并(ADR-0019 obs stable 后,~900 LOC,
  1-2w)— 独立 OpenSpec change
- **P5.6 G3**:DMC actor Go(DMC F1-D2 ≥0.30 后,~2000 LOC,2-3w)— 独立
  OpenSpec change

本 change 不实施 P5.5 / P5.6,仅在 design/tradeoffs 内 plan。

## 11. Cross-references

- 主 design → [`../design.md`](../design.md)
- Migration plan → [`../design/migrations.md`](../design/migrations.md)
- Tools layout → [`../design/tools-layout.md`](../design/tools-layout.md)
- Risks(R-H hidden import 残留)→ [`../design/risks.md`](../design/risks.md) §8
- CLAUDE.md repo layout 当前 → 顶部 "Repo Layout" 段
