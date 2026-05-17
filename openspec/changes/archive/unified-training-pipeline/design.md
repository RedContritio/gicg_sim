---
last_updated: 2026-05-16
status: ARCHIVED
schema_version: 0
change_id: unified-training-pipeline
---

# Design Retrospective — unified-training-pipeline

> Archive-time 摘要(per `openspec-policy/archive-workflow.md` Step 4)。
> Active 阶段的详细设计内容保留在 `./design/` 子目录(10 subtopic)作历
> 史 implementation record;本文仅 verdict + tradeoffs revisited +
> surprises + spec delta summary。

## Verdict

**Success**:P0-P5 8 sub-task ship(8 commits)+ P6 archive(本 commit),
5 paradigm 全部通过 unified `tools/run.py` 接入,`training/framework/` 删
除,5 paradigm spec + config-schema + tools-layout 7 个新 capability spec
ship。Cross-paradigm code reuse 实现(core/ vs paradigms/<name>/ 二分)。

## What we built

- **`training/core/`** — paradigm-agnostic infra:6 protocol / pipeline
  driver / network encoder+heads / buffer family / actor+inference / eval
  worker / opponent registry / config loader(P3-A.1 - A.4)
- **`training/paradigms/<name>/`** × 5 — 各 paradigm adapter 接入 6
  protocol(P3-B DMC / P4-AZ / P4-BC / P4-PPO / P4-CFR);legacy 子目录保
  留旧实现作 reproducibility 锚点
- **`tools/run.py` 单入口** — paradigm dispatch by `meta.paradigm`;5 个
  paradigm-specific launcher 替代
- **`tools/{eval,debug,probe,profile,bench,replay,dataset,_archived}/`**
  分类(P5-G);`configs/{active,smoke,shipped,_archived,<paradigm>}/`
  子目录化(P5-H)
- **7 个新 capability spec** ship 进 `openspec/specs/`:paradigm-{az,bc,
  cfr,dmc,ppo} + config-schema + tools-layout(本 P6 archive 合入);
  training-architecture SHALL 2 详化 + ADD SHALL 13-17

## Phase 实施(实际)

| Phase | Status | Commit(s) | Note |
|---|---|---|---|
| P0 | done | (8 commits 早于本 change) | OpenSpec 基建 + spec 骨架 |
| P1 | done | (9 commits 早于本 change) | 历史迁移 + paradigm dossier |
| P2 | done | `9c54ad6` | 本 change 落盘(proposal + design + tasks + spec delta) |
| P3-A.1 | done | `44b1186` | core/ 6 protocol + config layer + pipeline driver |
| P3-A.2 | done | `7a75097` | core/{network,buffer} paradigm-agnostic |
| P3-A.3 | done | `c5869df` | EpisodeRunner + NetworkProvider + IPC scaffold |
| P3-A.4 | done | `d47f6f1` | OpponentRegistry + PeriodicEval + statistics |
| P3-B | done | `b88986e` | DMC adapter ship + smoke verify(first migration) |
| P4-BC | done | `77943db` | BC first-class adapter |
| P4-AZ | done | `8ebc7a6` | AZ adapter |
| P4-PPO | done | `8b6238e` | PPO adapter |
| P4-CFR | done | `826bf44` | CFR adapter |
| P4 registry | done | `e7b21cf` | paradigms/__init__.py registry consolidate |
| P5-A | done | `d8c4e51` | DMC mv to paradigms/dmc/legacy/ |
| P5-B | done | `8103631` | AZ mv to paradigms/az/legacy/ |
| P5-C | done | `ec902c2` | CFR mv to paradigms/cfr/legacy/ |
| P5-D | done | `3eeac2a` | PPO mv to paradigms/ppo/legacy/ |
| P5-E | done | `aeea894` | BC dedupe(az+ppo embedded → bc/legacy/) |
| P5-F | done | `f122ca6` | framework/ 删除 + 能力进 core/ + AZ legacy network |
| P5-G | done | `99b582d` | tools/ 重组(8 子目录) |
| P5-H | done | `04f687e` | configs/ 子目录化(active/smoke/shipped/_archived/<paradigm>) |
| P3.5 / P5.5 / P5.6 | **deferred** | — | Go 化 follow-up(memory feedback_go_optimization_opportunistic) |
| P6 | done | 本 commit | archive(spec delta merge + design retrospective + git mv) |

## Tradeoffs revisited

| Tradeoff | 预期 | 实际 | Note |
|---|---|---|---|
| D1 BC first-class | 抽出独立 paradigms/bc/,dedupe AZ/PPO embedded copies | confirmed;P5-E `aeea894` dedupe pass | BC 现在唯一可信入口 |
| D2 PPO 迁移 vs archive | 迁移保留复盘 + lever 验证 | confirmed;PPO 通过 unified pipeline reproducible | s021-s054 ablation 仍可 rerun |
| D3 framework/ 删除融入 core/ | 消除"framework + 5 stack"双层 | confirmed P5-F;framework/ 完全 0 残留 | core/network/legacy/ 收下 AZ-specific network as transitional |
| D5 老 tools 合并 vs 删除 | 优先合并,真无用 → `_archived/` | confirmed P5-G | `tools/launch_*.py` etc 没直接 rm,进 dispatch 或 `_archived/` |
| Async 进 core 而非 paradigm | N actor + K inference 进程拓扑通用 | confirmed P3-A.3 | EpisodeRunner + NetworkProvider 抽象屏蔽 paradigm 差异 |
| Local vs Remote inference | NetworkProvider 抽象,placement × device 二维正交 | shipped P3-A.3 | GICG 当前 ~5M params,默认 Local + CPU |

## Surprises(per P5 implementer reports)

1. **`framework/` 不是 AZ-specific** — P5-F 发现 framework 内 network +
   inference server 实际被所有 paradigm 引用(不仅 AZ)。Refactor 时整体
   迁 `core/` 而非"裁剪 AZ 部分"。`core/network/legacy/` 子目录是
   transitional holding(等 G2 cgo + encode 合并 follow-up 决定下一步)。

2. **`env_factory` 2-API 并存** — P3-A 写新 `core/env_factory.py`,P5-F
   保留 legacy `env_factory_legacy.py` 在 core/ 内(被 paradigms/<name>/
   legacy/ 引用)。两个 API 并存暂时不消除,待所有 paradigms/<name>/legacy/
   退役后统一 cleanup。

3. **Parallel dispatch workspace contention**(P5-A/B/C/D)— 4 paradigm
   并行 mv 时遇到 worktree 边界 contention,需串行 commit(see P5-A → B
   → C → D commits)。lessons:未来 mv 多 paradigm 在同一 commit message
   batch 化处理。

4. **BC dedupe 涉及 3 个 source point** — P5-E 发现 BC 不仅在 `training/
   az/bc_*.py` + `training/ppo/bc_*.py`,还有 ckpt eval / dataset gen 各
   有 paradigm-specific 副本。Full dedupe 比 P4-T2.9 estimate(LOC -600)
   实际 LOC -800+。

## Spec delta summary

本 change 对 `openspec/specs/` 的变化:

- **`training-architecture/spec.md`** — [MODIFY] SHALL 2(Paradigm
  protocol 详化方法签名)+ [ADD] SHALL 13-17(NetworkProvider /
  EpisodeRunner / paradigm spec / config-schema / tools-layout 引用)+
  Paradigm landscape 段更新(指向 `training/paradigms/<name>/`)+
  Cross-references 更新(指向 7 新 sibling spec)
- **`paradigm-az/spec.md`** — 新建,17 SHALL(A1-A6 算法核心 + tier)
- **`paradigm-bc/spec.md`** — 新建,16 SHALL(BC1-BC6 算法核心 + tier)
- **`paradigm-cfr/spec.md`** — 新建,17 SHALL(C1-C6 算法核心 + tier)
- **`paradigm-dmc/spec.md`** — 新建,18 SHALL(D1-D7 算法核心 + tier)
- **`paradigm-ppo/spec.md`** — 新建,17 SHALL(P1-P6 算法核心 + tier)
- **`config-schema/spec.md`** — 新建,18 SHALL(CS1-CS4 顶层段 +
  INHERITED_FIELDS + Placement R1-R7 + Loader strictness)
- **`tools-layout/spec.md`** — 新建,17 SHALL(TL1-TL5 目录组织 + 单入口 +
  子目录边界 + 老 tools 处理 + dataset gen 统一)

总计:7 新 capability spec(从 12 → 19)+ 1 现有 capability spec 扩展。

## Deferred to follow-up changes

- **P3.5 G1**(F1-Dn Go 化,~700 LOC,3-5d)— deferred,memory
  `feedback_go_optimization_opportunistic`:Go 化顺手改不主动启动,P3-P5
  完成时未触发独立 change
- **P5.5 G2**(cgo step + encode 合并,~900 LOC,1-2w)— deferred,ADR-0019
  obs stable 后再启动(独立 OpenSpec change)
- **P5.6 G3**(DMC actor Go,~2000 LOC,2-3w)— deferred,DMC F1-D2 ≥0.30
  后再启动(独立 OpenSpec change)
- **`core/env_factory_legacy.py` 退役** — 待所有 paradigms/<name>/legacy/
  退役后 cleanup
- **`core/network/legacy/`** — transitional;G2 follow-up 决定下一步

## Cross-references

- 主 capability spec(已 merge 本 change spec delta)→
  [`../../../specs/training-architecture/spec.md`](../../../specs/training-architecture/spec.md)
- 7 个新 capability spec(本 change ship 时新建)→
  [`../../../specs/{paradigm-az,paradigm-bc,paradigm-cfr,paradigm-dmc,paradigm-ppo,config-schema,tools-layout}/spec.md`](../../../specs/)
- Detailed implementation record(active 阶段写,保留作历史)→
  `./design/{core-protocols,pipeline-driver,network-provider,episode-runner,async-pipeline,config-layered,tools-layout,migrations,risks,tradeoffs}.md`
- Archive workflow SOP → [`../../../specs/openspec-policy/archive-workflow.md`](../../../specs/openspec-policy/archive-workflow.md)
- 历史 ADR → [`../../archive/0006-training-layout/`](../../archive/0006-training-layout/) +
  [`../../archive/0009-rl-paradigm-pivot-terminus/`](../../archive/0009-rl-paradigm-pivot-terminus/)
- Memory cross-refs → `project_training_layout` / `project_rl_routes_closure_2026_05_12` /
  `feedback_go_optimization_opportunistic`

## Status

- **Archive committed**:2026-05-16(P6,本 commit)
- **Lifecycle**:closed;follow-up Go 化 changes 独立启动
- **Reproducibility lock**:5 paradigm legacy/ 子目录 + 7 capability spec
  锚点保证 reproducibility 与可对照
