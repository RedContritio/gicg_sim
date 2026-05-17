> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **IMPLEMENTED 2026-05-15**
> - 实施 commit 链(2026-05-15 13:11-14:20):c67b9ba(remote/_common)→ 2da97a0(remote/run)→ a4e7181(PS-safe)→ 18206bb(win_status rename)→ c675f34(remote/sync)→ ce5049e(dmc 合并 single/mp entry)→ 4c43b92(nan_guard test failing-first)→ 3f3510c / 5ae3f7c(NaN guard impl)→ 2449ce6 / bb51d4d / 2278558(tools/eval paradigm registry)→ d818ff3(metrics_view + compare)→ 29b3966(remote/pull + build_engine)
> - 全部 12 task ✓
> - tools/eval/ + tools/remote/ + training/dmc/ refactor done

---

# DMC Phase 3.5 基础设施重构 — 实施计划

> 2026-05-15 落盘。对应 design doc:`docs/5_history/dmc_phase35_infra.md`(已归档)
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。子文件中 step 用 checkbox(`- [ ]`)。

**Goal:** 把 DMC 训练栈散落的 `dmc_*.py` 工具(ssh / eval / replay / status)重构成 paradigm-agnostic 子目录(`tools/remote/` + `tools/eval/`),合并 single/mp 训练 entry,并在 learner train step 加 NaN/inf fail-fast guard + 证据 dump。

**Architecture:**
- `tools/remote/` 通用 Windows GPU box 链(无 paradigm 耦合)。
- `tools/eval/` paradigm-agnostic dispatcher(本次仅填 `'dmc'` adapter,`'az'/'cfr'` 预留接口)。
- `training/dmc/` 内 actor-learner 模块去 `_mp_` 前缀:`_actor.py / _learner.py / train.py`,单 entry `run(cfg)`。Smoke 走 `num_actors=1` 单 actor,pilot 走 `num_actors=24`,通过同一驱动。
- NaN guard 写在 `_train_helpers.train_steps()`,触发即 `RuntimeError` 终止训练并 dump `nan_dump_<step>/{batch.pkl, pre_step.pt, diag.json}`。

**Tech Stack:** Python 3.13 / PyTorch / multiprocessing(spawn)/ TOML cfg / pytest

---

## 审计已确认(动手前不需再 grep)

- `tools/dmc_train.py:30-32` 引 `train_loop.run_smoke`,`tools/dmc_train_mp.py:30-32` 引 `mp_loop.run_mp_train`,两者都是 ~40 行薄壳。
- `train_steps()` 在 Task 5 删除 `train_loop.py` 后,唯一 caller 是 `_learner.py:run_learner_loop`;`artifacts_dir` 在 learner scope 已存在(line 93),直接透传。
- `cfg.num_actors` 已存在(`training/dmc/config.py:80`,default=4),只是 single-process 路径未读它。合并后 `cfg.num_actors=1` 即 smoke 行为。
- `dmc_mp_smoke.toml` 与 `dmc_stage3_smoke.toml` 差别仅 `num_actors / eval.enabled`;合并后由 `dmc_stage3_smoke.toml + num_actors=1` 覆盖。
- 现有 dmc 测试(`test_dmc_{config,loss,opponent_pool,replay}.py`)不 import 任何 driver / mp_loop / actor / learner,rename 不破坏现有测试。
- `tools/dmc_eval_ckpt.py` 与 `tools/dmc_dump_replay.py` 共用 `PeriodicEvaluator` + `_build_baseline_player`,合并后底层 evaluator 不变。
- design doc `dmc_phase35_infra.md:155-232` 含 NaN guard `train_steps()` + `_dump_nan_evidence()` 完整代码,Task 7 直接 copy。

---

## Task 总图(12 个,按 design doc D 节优先级)

| Phase | Task | 主要交付 | 文件 |
|---|---|---|---|
| A 远程 infra | 1 | `tools/remote/_common.py` — ssh/scp helpers | [01_remote.md](01_remote.md) |
| A | 2 | `tools/remote/run.py` — Windows 模块 entry 包装 | 01_remote.md |
| A | 3 | `tools/remote/sync.py` — Mac → Windows 同步 | 01_remote.md |
| A | 4 | `dmc_win_status` → `tools/remote/status{,.ps1}` | 01_remote.md |
| B DMC 重构 | 5 | rename `_mp_*` → `_actor/_learner/train`,合并 single/mp entry | [02_dmc_nan.md](02_dmc_nan.md) |
| B | 6 | TDD: `test_dmc_nan_guard.py`(failing) | 02_dmc_nan.md |
| B | 7 | NaN guard 实现 + `_dump_nan_evidence` | 02_dmc_nan.md |
| C eval | 8 | `tools/eval/_paradigm.py` + `_dmc_adapter.py` | [03_eval.md](03_eval.md) |
| C | 9 | `tools/eval/ckpt.py` 合并 `dmc_eval_ckpt` + `dmc_dump_replay` | 03_eval.md |
| C | 10 | `dmc_eval_daemon` → `tools/eval/daemon.py` + `--paradigm` | 03_eval.md |
| D 看结果+周工具 | 11 | `tools/eval/metrics_view.py` + `tools/eval/compare.py` | [04_view.md](04_view.md) |
| D | 12 | `tools/remote/pull.py` + `build_engine.py` | 04_view.md |

---

## 验收(全部完成后)

逐条对 design doc `dmc_phase35_infra.md` E 节核对:

- [ ] `tools/dmc_train.py configs/dmc_stage3_smoke.toml` 跑通(Task 5 覆盖)
- [ ] `tools/remote/run.py -- python -m tools.dmc_train configs/dmc_stage3_pilot.toml` 替代旧 ssh+powershell 链(Task 2 + Task 5 联合)
- [ ] 跑 pilot 触发 NaN → 终止 + 留 `nan_dump_<step>/` + raise(Task 7 fixture pass;真训触发由 user 后续执行)
- [ ] `tools/eval/ckpt.py --ckpts a b --record-replays --save-both-win` 替代旧两脚本联合(Task 9)
- [ ] `diff` 两 ckpt 的 yaml 输出可直接对比策略(Task 9 step 5)
- [ ] 全 pytest pass:`.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q`

---

## 不在本计划 scope

- 真训触发 NaN 的 root-cause 分析与修复(infra ready 后,user 跑 pilot 若再现 NaN 用 `nan_dump_<step>/` 离线分析)
- Stage 4 multi-char + char_pool 抽样 + 元素反应
- AZ / CFR paradigm 实际填充(本计划只留 `_paradigm.py` 接口)
- Windows 实测 24-actor pilot(infra ready 后单独执行)
