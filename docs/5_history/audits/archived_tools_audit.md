# tools/_archived/ 死代码 audit

> 2026-05-16(FU-W2.5d)report:`tools/_archived/` 下 18 个 .py / .sh 文件,
> 哪些在 active repo 内仍有引用、哪些可直接 `git rm`。
>
> 本文件是**决策候选材料**,不直接执行删除(待 user 批后单独 commit `git rm` + sync docs)。
>
> **2026-05-16 update(FU-W4-PPO)**:PPO legacy 全量退役时一并删除了
> `ppo_bc_eval_probe.py` / `ppo_calibrate.py` / `ppo_replay_check.py`
> (Dead 类)+ `ppo_eval_probe.py` / `ppo_launch.py`(Doc-only 类)
> + `ppo_multiseed_aggregate.py`(Live 类,test 同删)。后续审计请以
> 当前 `tools/_archived/` 实际文件列表为准。

## Method

对每个 `tools/_archived/<name>.{py,sh}`:

1. `grep -rln "tools\._archived\.<name>\|tools/_archived/<name>"`(全路径形式引用)
2. `grep -rln "<name>\.(py|sh)"`(bare-name 形式引用,覆盖 docstring / 注释 / shell command 等)
3. 排除:
   - self-reference(`tools/_archived/` 内部互引用 — 不算 active)
   - `docs/5_history/` 内引用 — 历史归档,不算 active
   - `openspec/changes/archive/` 内引用 — 已 archive 的 change,不算 active
4. 分类:
   - **Dead**:0 active 引用 — 可直接删
   - **Doc-only**:仅 docstring / comment / md 描述,无 active 代码 import / subprocess invoke — 可删 + sync docs
   - **Live**:active 代码(test / module / config 等)以 import 或 subprocess 形式依赖 — 保留(或同步迁回 `tools/`)

`tools/_archived/__init__.py` 为空 package 标记,**不参与分类**(伴随其余文件一起去留)。

## Summary

- Total `tools/_archived/` files: 19(18 audit + `__init__.py`)
- **Dead**(可删): 8
- **Doc-only**(可删 + 同步 docs): 9
- **Live**(保留 / 修复 import): 1
- `__init__.py`:伴随 Dead/Doc-only 全删后可一并删除;若 Live 保留则 `__init__.py` 同保留

## Dead(0 active 引用,可删候选)

| File | 备注 |
|---|---|
| `tools/_archived/cfr_post_gauntlet.py` | 仅被 `tools/_archived/run_cfr.py` import(self-ref) |
| `tools/_archived/cfr_presets.py` | 仅被 `tools/_archived/run_cfr.py` import(self-ref) |
| `tools/_archived/greedy_ladder_stage1.py` | 0 active 引用 |
| `tools/_archived/greedy_tiebreak_audit.py` | 0 active 引用 |
| `tools/_archived/ppo_bc_eval_probe.py` | 0 active 引用 |
| `tools/_archived/ppo_calibrate.py` | 0 active 引用 |
| `tools/_archived/ppo_replay_check.py` | 0 active 引用 |
| `tools/_archived/run_r008_gauntlet.sh` | 0 active 引用 |

## Doc-only(可删 + 同步 docs)

引用源均为**文档表述 / docstring / 注释**,**无任何 active import 或 subprocess invoke**。
删除文件后,需同步删除 / 更新下列文档引用。

### `tools/_archived/dmc_train.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `tools/run.py` | L5 | module docstring 历史说明 |
| `training/paradigms/dmc/__init__.py` | L5 | package docstring 历史说明 |
| `training/paradigms/dmc/legacy/train.py` | L9 | module docstring 历史说明 |
| `training/paradigms/dmc/PLAN.md` | — | plan doc 提及 |
| `training/paradigms/dmc/notes.md` | — | notes 提及 |
| `configs/smoke/dmc_stage3_smoke_v2.toml` | L5 | TOML 注释("Old cfg ... kept as fallback") |
| `openspec/specs/tools-layout/spec.md` | L16 / L63 | spec 列出 TL2.1 待 merge 入口 |

### `tools/_archived/eval_bc_ckpt.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `openspec/specs/tools-layout/spec.md` | L66 | spec TL2.4 ckpt eval merge list |

### `tools/_archived/launch_config.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `tools/run.py` | L5 | module docstring 历史说明 |
| `tools/_meta/multi_seed_launch.py` | L8 | module docstring 描述"replaces ... launch_config" |
| `training/paradigms/az/__init__.py` | L6 | package docstring 历史说明 |
| `docs/1_specs/training/implementation.md` | L398 | 目录树示意 |
| `docs/1_specs/engine/dsl/conventions.md` | L197 | DSL preload 说明 |
| `openspec/specs/tools-layout/spec.md` | L63 | spec TL2.1 merge list |

### `tools/_archived/ppo_bc_launch.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `training/paradigms/bc/legacy/README.md` | L8 | dedupe rationale 表格历史 ckpt 来源说明 |
| `docs/2_decisions/adr-0007-ppo_bc_warmstart.md` | L149 | ADR launcher 选项历史 |

### `tools/_archived/ppo_launch.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `training/paradigms/ppo/legacy/run.py` | L6 | module docstring 历史说明 |
| `training/paradigms/ppo/__init__.py` | L6 | package docstring 历史说明 |
| `training/paradigms/ppo/legacy/train.py` | L4 | module docstring 历史说明 |
| `docs/4_runs/registry.md` | L56 | 历史 PPO run launch 命令 |
| `docs/2_decisions/adr-0007-ppo_bc_warmstart.md` | L149 | ADR launcher 选项历史 |
| `openspec/specs/tools-layout/spec.md` | L17 / L64 | spec TL2.1 merge list |

### `tools/_archived/ppo_eval_probe.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `docs/2_decisions/adr-0007-ppo_bc_warmstart.md` | L188 | ADR teacher probe 表述 |

### `tools/_archived/run_cfr.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `docs/paradigms/cfr/README.md` | L96 | 链接到旧入口(标 "若存在") |
| `docs/4_runs/_individual/r008_plan.md` | L44 / L51 / L202 | r008 历史 plan 的 shell 命令 |
| `openspec/specs/tools-layout/spec.md` | L63 | spec TL2.1 merge list |

### `tools/_archived/select_bc_ckpt.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `openspec/specs/tools-layout/spec.md` | L67 | spec TL2.4 ckpt eval merge list |

### `tools/_archived/test_dice_scheduling.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `training/paradigms/dmc/README.md` | L80 | F1-D2 反例脚本路径说明 |
| `training/paradigms/dmc/notes.md` | L399 | F1-D2 反例脚本路径说明 |

## Live(保留 / 需修 import)

### `tools/_archived/ppo_multiseed_aggregate.py`

| 引用源 | 行号 | 性质 |
|---|---|---|
| `training/tests/test_ppo_multiseed_aggregate.py` | L61 | subprocess 调 `python -m tools.ppo_multiseed_aggregate` |

**注意**:test 写的是 `tools.ppo_multiseed_aggregate`(旧路径),而文件已搬到 `tools._archived.ppo_multiseed_aggregate`。
当前 test 形式上已 broken(import 阶段不报错,run 阶段 4 个 case 必失败)。本次审计**没跑 test 验证**
(超出 audit 范围),但 collect-only 显示 4 个 test 未 skip 仍 collect。

两个修复路径:
1. **保留 `_archived` + 修 test**:把 test 内 `tools.ppo_multiseed_aggregate` 改成 `tools._archived.ppo_multiseed_aggregate`(最小动作)
2. **删 _archived + 删 test**:若 PPO 栈 closure(ADR-0009)后 multiseed aggregate 工具确认不再需要,test 也一并删

二选一由 user 定。

## Action(待 user 批)

user 批后,**单独 commit** 执行:

1. **Dead 类**(8 file)+ `__init__.py`(若 Live 也清掉则同删):
   ```
   git rm tools/_archived/cfr_post_gauntlet.py
   git rm tools/_archived/cfr_presets.py
   git rm tools/_archived/greedy_ladder_stage1.py
   git rm tools/_archived/greedy_tiebreak_audit.py
   git rm tools/_archived/ppo_bc_eval_probe.py
   git rm tools/_archived/ppo_calibrate.py
   git rm tools/_archived/ppo_replay_check.py
   git rm tools/_archived/run_r008_gauntlet.sh
   ```

2. **Doc-only 类**(9 file):`git rm` + sync 全部 docs / docstring 引用(每文件一个 commit 便于 review)。
   - 注意 `openspec/specs/tools-layout/spec.md` 的 TL2.1 / TL2.4 merge list 若已完成 merge,
     可同步标 "DONE";若 spec 还在 active 状态,需 user 决定是否同步更新 spec 章节。

3. **Live(`ppo_multiseed_aggregate.py`)**:按上节二选一,**先 user 决策再动**。

## 备注

- 本 audit **仅 grep 静态引用**,**未运行 test suite** 验证 Live 类的 runtime 依赖。
  user 批准 Dead/Doc-only 删除前,建议跑一次 `.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q`
  作 baseline。
- `__init__.py` 为 0-byte package marker;若 Dead+Doc-only 全删后只剩 `ppo_multiseed_aggregate.py`,
  可继续保留 `__init__.py` 让 `tools._archived` 仍为合法 package。
