# AZ paradigm 彻底重写 — legacy retire

**Status:** Active change(handoff to new session)
**Date opened:** 2026-05-16
**Supersedes:** None(unified-training-pipeline `archive/` 已结案;本 change 是 FU-W4-AZ 的延续)
**Affected specs:** `paradigm-az/spec.md`(MODIFY 实施细节)

## Why

P0-P6 主线 + FU-W1..W3 + W4 partial 结束后,4 paradigm legacy retire 结果不一:

| Paradigm | Status | Commit |
|---|---|---|
| DMC | ✅ retire complete | `decb4a8` + `73c6ed7` |
| PPO | ✅ retire complete | `2e5bc6f` |
| CFR | ✅ 评估为不该 retire(intentional shim by design) | 0 commit |
| **AZ** | **❌ BLOCKED**(strict isolation 下 scope 不可达) | 0 commit |

AZ 在 FU-W4 BLOCKED 的根因:
1. legacy 是 production 实施(非 wrap target)— MCTS Go ctypes / IS-MCTS / determinize Bayesian posterior / inference pool / selfplay arena 都是核心算法,不能简单 inline
2. **47 external refs** 横跨 11 active tools(debug/probe/profile/bench)+ 2 core 文件 + 20+ non-test_az tests + docs
3. production fallback ckpt 路径(r009/r010-012)必须保留 — `core/matchup/loaders.py:181-182` 通过 `legacy/network/agent.Agent` 加载 r009 BC ckpt(vs F1-D2 = 0.75,ADR-0009 钦定)
4. FU-W4 strict isolation 限本 paradigm `paradigms/az/` 内,但 retire 必需 scope 跨 tools/core/tests 33+ 文件

user 决策:**接受高 risk + 大 scope,彻底 rewrite**。本 change 是 handoff,新 session resume 实施。

## What

1. **Adapter rewrite 完全脱离 legacy**:`paradigms/az/{paradigm,collector,policy,loss,network,config,buffer}.py` 重写,直接使用 `core/` 基础设施 + inline 必要 AZ-specific 逻辑(MCTS / selfplay / determinize)
2. **保留 Go-side bindings**:`gicg_mcts/` Go-to-Go binding 不重写(MCTS L3 实施稳定;Python ctypes wrapper 可保留 / 重写在 adapter 内)
3. **Update 47 external refs**:11 active tools + 2 core 文件 + 20+ tests + docs 全部切到 adapter API
4. **Preserve r009 ckpt loadability**:rewrite 后 `core/matchup/loaders.py` 加载 r009 ckpt + run gauntlet 仍重现 vs F1-D2 = 0.75(ADR-0009 production guarantee)
5. **Git rm `paradigms/az/legacy/`** — 删 31 files / ~3680 LOC

## Affected specs

- `openspec/specs/paradigm-az/spec.md` — MODIFY:更新实施引用 path(从 `legacy.X` 到 `paradigms.az.X`),adapter 自足
- 可能 `openspec/specs/training-architecture/spec.md` — MODIFY(若架构有变)
- `openspec/specs/openspec-policy/` — 不变

## Out of scope

- **不重写 Go-side MCTS / gicg_mcts**(Go 化策略 per memory `feedback_go_optimization_opportunistic` — 顺手改,不主动)
- **不破坏 r008/r009 reproducibility**(per ADR-0009 + C6.2 spec)
- **不改 AZ algorithm semantics**(只重组 code organization,不改 PUCT / determinize / value head 逻辑)

## Risks

详 `design.md` Risks 段。3 大类:**production ckpt 不可加载**、**Go ctypes binding 移植**、**20+ tests 大范围改动**。

## Subtopics

详 [design.md](./design.md)(architecture + risk + migration path)+ [tasks.md](./tasks.md)(5 phase 实施 task)。
