# 架构统一主线剩余 11 项 — agent-driven 并行推进 plan

> 2026-05-16 开。承 `project_architecture_unification_remaining_2026_05_16` memory + `openspec/changes/az-paradigm-rewrite/`(active change handoff)。
>
> **执行模式**:subagent-driven-development + dispatching-parallel-agents 混合。独立 domain 并行;同域 sequential。每个 implementer 走 TDD + 自审,后接 spec compliance review + code quality review 双闸。
>
> **测试纪律**(user 2026-05-16 钦定):**测试按"应有行为"写,不按"当前实现"写**。RED 阶段先描述目的,看 fail,再写最小 GREEN。

## Wave 拆分(依赖图)

```
Wave A (5 并行)         Wave B (sequential)    Wave C (sequential)
  ┌─ A1 #2              ┌─ B1 #3                ┌─ C1 #1 Phase 1
  ├─ A2 #6              └─ B2 #4 ── (after B1)  │     T1.1 → T1.2 → T1.3 → T1.4 verify → T1.5 commit
  ├─ A3 #9                                       └─ (Phase 2-5 留下次 session,active change handoff)
  ├─ A4 #10
  └─ A5 #11

Wave D (依赖 #1)        Wave SKIP
  └─ E1 #5                #7 / #8(ROI 低,推荐不做)
```

## 各 wave 任务详

### Wave A — 完全独立,并行 dispatch

| ID | task | 文件 scope | 测试目的(按应有行为) | acceptance |
|---|---|---|---|---|
| A1 | #2 DMC dead ref | `tools/eval/_paradigm.py + ckpt.py + daemon.py` | "用户 `--paradigm dmc` 入 eval/daemon 能正确 load DMC config" | smoke: `python -m tools.eval.ckpt --paradigm dmc --help` 不 ImportError |
| A2 | #6 tools/_archived/ 批删 | `tools/_archived/{8 dead + 9 doc-only}` + sync 6 docs/specs | "active codepath 删除后 0 import 引用;docstring 提及保留(历史叙述)" | grep-clean + pytest no regression |
| A3 | #9 OpenSpec index 白名单 | `tools/_meta/check_openspec_indices.py` | "主 spec.md 含 `./<file>.md` placeholder 不被 checker 误报缺链" | 新增 `test_check_openspec_indices_placeholder.py` 覆盖该 case |
| A4 | #10 opsx:archive 自动化 | 新建 `tools/_meta/openspec_archive.py` | "工具执行后 archive 结果 byte-equivalent manual 5 步" | golden: 用 `archive/unified-training-pipeline` 反向重演,diff = 0 |
| A5 | #11 paradigm SOP 文档 | 新建 `openspec/specs/training-architecture/subtopic-paradigm-onboarding.md`(或同等) | OpenSpec R1+R2+R3 index check + 描述完备(含 5 paradigm 历史教训) | `check_openspec_indices` 通过 + manual review |

### Wave B — sequential 链(#3 → #4)

| ID | task | 文件 scope | 测试目的 | acceptance |
|---|---|---|---|---|
| B1 | #3 BC PPO variant 退役 | `paradigms/bc/legacy/{bc_train_ppo,bc_losses_ppo,_ppo_net}.py` + `test_bc_hard_target.py` | **重写测试**:测"BCParadigm 在 hard-target 数据上能学到正确 policy"(应有行为),不测 PPO variant 实现细节 | redirect 后 test pass,bc/legacy 文件 git rm |
| B2 | #4 gen_bc.py dedupe | `tools/dataset/gen_bc.py` | "dataset 输出单一 schema(AZ-shape)适用全 BC paradigms" | smoke gen 后 BCParadigm load 通 |

### Wave C — #1 AZ rewrite Phase 1(单 implementer,内部 sequential)

T1.1-T1.5 同 adapter 改组,**不可并行**。每子 task TDD。

测试目的:
- T1.1 `paradigms/az/config.py`:"AZParadigmConfig 含 AZAgent runtime 必需全字段"(不测 legacy AZConfig 形状)
- T1.2 `paradigms/az/loss.py`:"adapter loss 直接 import `core/network/legacy/loss.az_losses`,不 import `legacy/az`"(测 import 拓扑,非数值)
- T1.3 `paradigms/az/network.py` partial:"basic head 组合直接用 core/network/{encoder,heads,actor_critic};Agent class 保 reference 待 Phase 2"
- T1.4 verify gate:`pytest -n 4 training/tests/test_az_paradigm.py` 34 全 pass
- T1.5 commit(单 commit 整 Phase 1)

**Phase 2-5 留下次 session** — `openspec/changes/az-paradigm-rewrite/tasks.md` 已 handoff。

### Wave D — 依赖 #1 完成(本 session 不动)

- E1 #5 `core/env_factory_legacy.py + core/network/legacy/` cleanup — 必 `paradigms/az/legacy/` 彻底删后才动

### Wave SKIP — 不推荐

- #7 23 pre-existing pytest fail:env/platform 问题,ROI 低
- #8 r009/r011/r012 registry:dossier 引用已 OK

## Status (2026-05-16 ship)

本 plan 在 2026-05-16 session 中执行。落地总览:

- **Wave A 5/5 DONE**:
  - A1 #2 DMC dead ref → `c4eeb60`
  - A2 #6 tools/_archived/ 批删 → `b816c32` + `55c607c` + `1ffdd33`(含 regression guard)
  - A3 #9 OpenSpec index 白名单 → `ade04ea` + `adc6db2`(trim 294 LOC)
  - A4 #10 opsx:archive 自动化 → `0755349` + `38603a0`(working-tree precheck)
  - A5 #11 paradigm SOP → `ffe2973` + `bfe302e`(citation fixes)
- **Wave B 2/2 DONE**:
  - B1 #3 BC PPO variant 退役 → `2d0584b` + `1cb1bec`(test dead var)
  - B2 #4 gen_bc.py dedupe → `2388834` + `0f62627`(dead teacher_side)
- **Wave C #1 Phase 1 DONE**:
  - T1.1-T1.5 → `ead430f` + `e779c21`(Phase 2 seam lock test)+ `a61ce7b`(SKILL.md sync)
  - Phase 2-5 留下次 session;`openspec/changes/az-paradigm-rewrite/tasks.md` 已 handoff(`8e426ff`)
- **Wave D**:依赖 #1 Phase 5 完成才动,本 session 不动
- **Wave SKIP** #7/#8 保持不动

共 17 commits ship。每 commit 经 spec reviewer + code quality reviewer 双闸。
本 session tail-end hygiene cleanup 见后续 commit(本 plan 提交进 docs/3_plans/)。

## TDD per implementer

每 dispatch 携带:

```
TDD 强制流程:
1. RED:先按"应有行为"写测试(测目的,不测当前实现)
2. 跑测试,确认 fail with expected reason
3. GREEN:最小代码使测试 pass
4. 跑测试,确认 pass
5. REFACTOR(可选)
6. 自审(对照 task spec 检查 over/under-build)
7. report status(DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED)
```

## 2-stage review per task

每 implementer 报 DONE 后:
1. spec reviewer(`./spec-reviewer-prompt.md`):对照本 plan task 描述,验"做了应做 + 没做不应做"
2. code quality reviewer(`./code-quality-reviewer-prompt.md`):review commit SHA,验代码质量(命名/重复/边界/测试)

review fail → implementer 同 subagent 修 → re-review。

## Out of scope

- Go 化(per memory `feedback_go_optimization_opportunistic`)
- v_phase2 真实卡池(主线 B,不在本 plan)
- DMC GPU stage 3 train(训练 run 非架构)
- `#1 Phase 2-5` AZ 核心 rewrite(active change handoff,留下次 session)
