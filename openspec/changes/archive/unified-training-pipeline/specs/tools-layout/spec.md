---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: tools-layout
change_id: unified-training-pipeline
---

# Spec delta — tools-layout(new capability)

> 新 capability spec。`tools/` 目录组织 + 单训练入口 + paradigm-specific
> 老工具合并/分类规约。锚定 D5 决策(老 tools 合并分类,不直接删)。

## 1. Purpose

`tools/` 目录在 PPO + AZ + CFR 并存时期演化为 paradigm-specific 入口分
散:`tools/launch_*.py` × N + `tools/run_*.py` × N + `tools/dmc_train.py`
+ `tools/ppo_launch.py` 等。本 spec 治理:

- **单训练入口**:`tools/run.py` 唯一 entry,paradigm 从 `meta.paradigm`
  dispatch
- **功能分类子目录**:eval / remote / debug / probe / profile / bench /
  replay / dataset / cards / _meta
- **老 tools 合并/分类**:不直接 rm,合并到 `run.py` 或 mv 到子目录
- **`_archived/`**:真无用工具进归档,git history 保留

## 2. Scope

**In scope**:
- `tools/` 顶层目录约束:谁可以放顶层,谁必须进子目录
- 子目录命名 + 内容边界(paradigm-agnostic)
- `tools/run.py` 单入口 SHALL + paradigm dispatch
- 老 tools 处理规则(merge / mv / archive)
- `tools/_meta/` 子目录 — meta 工具(check_*.py / inheritance.py)

**Out of scope**:
- 各工具内部实现细节(本 spec 只约束目录布局)
- Pre-commit hook 接入(`.githooks/` 配置)— `CLAUDE.md` 治理
- `docker-compose.yml` / Dockerfile — `tools/_meta/dc.sh` wrapper 之外
  的 container 配置不在本 spec 边界
- Notebooks / Jupyter scratch — 走 `notebooks/`(若引入),不混入 `tools/`

## 3. Core SHALL invariants

### TL1. 目录组织

1. **TL1.1** `tools/` SHALL organize by function — kebab-case 子目录:
   `eval/` / `remote/` / `debug/` / `probe/` / `profile/` / `bench/` /
   `replay/` / `dataset/` / `cards/` / `_meta/`(+ `_archived/`)。
2. **TL1.2** `tools/<subdir>/` SHALL be **paradigm-agnostic** by design —
   工具不写 paradigm-specific switch;paradigm 区分通过 cfg dispatch。
3. **TL1.3** `tools/` 顶层 SHALL contain only:`run.py`(训练入口)+
   `dc.sh`(docker wrapper,P0 deprecated → 进 `_meta/` Phase 5);no
   paradigm-named file at 顶层。

### TL2. 单训练入口

4. **TL2.1** `tools/run.py` SHALL be the **唯一**训练入口。Usage:
   `python -m tools.run <cfg.toml>`。
5. **TL2.2** `tools/run.py` SHALL dispatch to paradigm by `meta.paradigm`
   cfg 字段(per `config-schema/` SHALL CS1.3);SHALL NOT 硬编码 paradigm
   list inline。
6. **TL2.3** Pre-existing paradigm-specific entries
   (`tools/launch_config.py` / `tools/run_cfr.py` / `tools/dmc_train.py` /
   `tools/ppo_launch.py`)SHALL **merge to `tools/run.py`** + dispatch,
   SHALL NOT 并存(per D5)。
7. **TL2.4** Ckpt eval entries(`tools/eval_bc_ckpt.py` /
   `tools/dmc_eval_ckpt.py` / `tools/select_bc_ckpt.py`)SHALL merge to
   `tools/eval/ckpt.py`(P0-T8 ship)。

### TL3. 子目录内容边界

8. **TL3.1** `tools/eval/` SHALL contain paradigm-agnostic eval scripts
   (`ckpt.py` / `gauntlet.py` / `arena.py`);SHALL NOT 写 paradigm-named
   eval(per TL1.2)。
9. **TL3.2** `tools/remote/` SHALL contain remote service utilities
   (eval_service launch / inspect / SHM debugging);P0-T8 ship。
10. **TL3.3** `tools/debug/` SHALL contain `diag_*.py` 7 scripts(P5 mv
    from 顶层)— ad-hoc diagnostic,paradigm-agnostic by typed signal
    inspection。
11. **TL3.4** `tools/probe/` / `profile/` / `bench/` / `replay/` /
    `dataset/` / `cards/` SHALL follow same pattern — mv legacy 顶层文件
    进对应子目录(per D5)。
12. **TL3.5** `tools/_meta/` SHALL contain repo meta tools(check_line_limits /
    check_openspec_indices / inheritance / openspec_archive / register_run /
    multi_seed_launch / send_matchup_* / dc.sh)— **never** training
    workflow,**only** repo / docs hygiene。

### TL4. 老 tools 处理(merge / mv / archive)

13. **TL4.1** **合并优先 over 删除**(D5 决策)— 老 tools 不直接 rm,
    优先合并到对应入口或 mv 到分类子目录。
14. **TL4.2** **真无用** tools(grep 0 引用 + 无 reproducibility 价值)→
    mv 到 `tools/_archived/`,git history 保留。**SHOULD** 配 batched
    approval(单 commit 多文件 archive,带 commit message 注明每文件
    rationale)。
15. **TL4.3** Archive 后 SHALL NOT rerun(`_archived/` 仅作 git history
    indexable 占位)。如需复活,SHALL 走 OpenSpec change un-archive。

### TL5. Dataset gen 统一

16. **TL5.1** BC dataset 生成 SHALL through `tools/dataset/gen_bc.py`
    (统一入口),paradigm-specific dataset gen
    (`tools/ppo_gen_bc_data.py` / `tools/gen_bc_dataset_az.py`)SHALL
    merge to `gen_bc.py` + cfg dispatch。
17. **TL5.2** Dataset inspect tools(`tools/dataset/inspect.py`)SHALL be
    paradigm-agnostic,操作 standardized BC dataset format。

## 4. Cross-references

- D5 决策来源 → [`../../design/tools-layout.md`](../../design/tools-layout.md) §2
- 主 training architecture → [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md)
  SHALL #12(Single entry tool)
- Cfg dispatch 接口 → [`../config-schema/spec.md`](../config-schema/spec.md)
  SHALL CS1.3
- Phase 5 实施(物理 mv)→ [`../../tasks/phase5-physical-mv-tools.md`](../../tasks/phase5-physical-mv-tools.md)
- Pre-commit hook 路径 → `CLAUDE.md` pre-commit hooks 段

## 5. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 3(`tools/run.py` ship + paradigm dispatch)+
  Phase 5(物理 mv + `_archived/` 整理)
- **Revision triggers**:
  - 新功能子目录(如 `notebooks/`)加入 → 子目录列表更新
  - `_archived/` 大量积累 → 评估是否 rm(grep 检查 + commit history 保
    留即可,目录不必长存)
