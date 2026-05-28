---
last_updated: 2026-05-28 (I29 R7 N-subprocess 闭环 ship / Stage 3 Win pilot 跑出 DMC policy collapse 验证 / minimax DeepCopy + wire schema lock + GPU stream priority + SHM race-aware metric 一并 ship / C1 选 A 准备 full 1M continue)
status: LIVE
---

# Status — 现在在哪

## 新 session 第一站

> 进入 docs 的第一站。读完这一页 30 秒应能回答:**现在在干什么 / 困难是什么 / 下一步怎么走**。
>
> 三个入口互补:
> - **OpenSpec**(规约 + change workflow): [`openspec/project.md`](../../openspec/project.md) — 项目层 spec / SHALL invariants
> - **Paradigm landscape**(科研复盘): [`docs/paradigms/README.md`](../paradigms/README.md) — 5 paradigm × verdict × 数据
> - **本页**(LIVE 状态):当前 phase / 困难 / 下一步
>
> docs/ 编号导航(P1 后): `0_status` → `1_specs` (待迁 `openspec/specs/`) → `2_decisions` (已迁 `openspec/changes/archive/`,mirror 保留) → `3_plans` (active only) → `4_runs` (experiment log) → `5_history` (archived plans + 复盘)。
>
> LIVE 状态文件:phase / 里程碑 commit 内更新。

## 元任务

**两条主线并行**:
1. **算法可学性验证**:GICG 这种 imperfect-info mirror Nash 游戏,RL/AZ/CFR 哪个栈能学
2. **正式版卡池 + DSL 形态稳定**:引入七圣召唤实际游戏全量卡牌 + 平衡性版本管理,验证 algorithm scalability + 锁定 DSL spec

不是训 SOTA agent。

## 当前 phase(2026-05-28 EOD)

### 0. Stage 3 Win pilot + DMC policy collapse 验证 + 多 perf/safety fix ship(2026-05-28,7 commits)

**Stage 3 Win N=16 production pilot 跑通 → 主动停于 3.7%(iter 2500)** 做 policy 诊断:
- ckpt vs F1-D2 wp **0/256 (CI 上限 1.5%)** vs random ε=1.0 拿 22%(CI 11-39%)— **CI 完全不重叠 → DMC 早期 policy collapse 固化**(PLAN.md §A.2 机制 verified:ε=0.05 + MC return ±1 → MSE depress 被选 action → argmax 永选 never-chosen 烂手 self-reinforcing)
- **C1 决策:走路径 A(继续训 full 1M,12-16h),赌后期 self-recover**;失败则进 PLAN.md §A.4 closure
- 详:私有 memory `project_stage3_pilot_policy_collapse_2026_05_28`

**同 session ship 7 commits(`b5f45e2..836be01`)分三批**:

| 类 | Commit | Scope |
|---|---|---|
| Stage 3 unblock | `b5f45e2` | `tools/eval`:random-baseline policy-collapse 诊断 + Win remote rsync fallback |
| H2 root cause | `d5987d0` | `gicg_actor/dmc/greedy_player`:minimax 热路径 DeepCopy → SnapshotPooled(bench 1.45x ns/op + 16→0 alloc + 32 KB→0 byte;原 budget cap 是 GC churn workaround,改完 root cause 后 production cfg 可恢复 unbounded) |
| C3 cross-lang safety | `a613c6e` | `wire/paradigm-payload`:加 `PayloadVer u8` prefix(DMC/AZ/PPO 各独立版本)+ decode mismatch fail-loud + DMC byte-layout golden test |
| Pre-existing | `b3609b6` | `configs/dmc/eval_stage3_b_v_legacy`:补 `[meta] paradigm = "dmc"`(FU-W1B schema) |
| H3 visibility | `2804539` | `training/core/actor/ipc`:`peek_count_and_full_at_head` race-aware ring 探针 — 返 `(count, n_full_at_head)` 区分 over-reserve race vs actor stall(B-go-sustained-collection-deadlock 调试必备) |
| H1 GPU perf | `049e722` | `training/core/actor`:InferenceServer forward 走 `priority=-1` CUDA stream — 抢占 train backward kernel 间隙,降 inference tail latency(实测 run 149 GPU 7-92% util 抖动信号) |
| Pre-existing | `4e4257a` | `gicg_engine/dsl/audit_test`:补 8 个漏列 builtin whitelist(`declare_reaction` / `set_reaction_kind` / `on_shield_absorb` / 4 个 `on_damage_*` / `remove_support`) |
| Pre-existing | `836be01` | `gicg_engine/tests/set_hidden_state`:sort map iter 消除偶发 fail |

**挂起的项**(估 ROI 排序,本 session 决策不做):
- **H4 GOMEMLIMIT validation**(~50 LOC):Win 长跑 OOM 防 silent regression — *方案 C 折中已规划,下个 session 开*
- **IPC Risk #5 stale-episode 检测**(~30 LOC):`_go_assembler` LRU evict 加 stale + warn log,给 C1 long-run debug visibility — *已规划,下个 session 开*
- **H5 Lua interp 优化**(LONG TERM):LuaJIT 替换违反立约(`openspec/project.md:33` "自研解释器,非 LuaJIT")+ 8000 LOC 自研 + IR 系统全推倒数月工程;真要做需先 profile 验证占比(估 10-15% 待真测),路径是 bytecode cache / hot hook 移到 Go-native,不切外部 VM
- **M1 OpenSpec archive 重复 ID**(~1h):`0006/0007` 双 ID 冲突 + I29 缺 ADR mirror
- **M3 docs/1_specs vs openspec/specs truth 重复**(2-3h):20 vs 60 文件 overlap,需 audit 整理

### 0a. core/network 重设计 + 5 paradigm 完全统一 ship(2026-05-17,34+ commits)

单 session 跑完 architecture unification 大主线:
- **`core-network-generic-promotion`** parent change(13 commits,Phase 0-6 ship):generic `ActorCritic` thin composition + DI `AgentBase` + `typed_damage` first-class + `core/network/legacy/` 物理删除 + 5 paradigm 全切 generic backbone + ckpt self-describing schema + symmetric smoke template + `tools/runs/` CLI suite
- **6 follow-up changes**(15 commits):docs-pre-redesign-refs-sweep + env-factory-unification(3-arg canonical)+ cfg-schema-unification(ObsShape + ParadigmConfigBase + version)+ ppo-structural-backbone-migration(PPO 切 generic)+ cfg-toml-restructure-paradigm-scoped(hybrid TOML)+ paradigm-smoke-full-tier(opt-in `@pytest.mark.smoke_full`)
- **#7 ppo-cfg-shape-alignment**(1 commit):闭 5/5 paradigm cfg dataclass 完全对称(D3 closure)
- 5 paradigm:**AZ/BC/DMC/CFR/PPO 全部走 `make_actor_critic` generic ActorCritic backbone**(spec invariant A4 100% 闭环)
- 完整统一度 ~92-95%(剩 5% 是 CFR algorithm-inherent paradigm-specific intentional divergence per D-207)
- 详:`project_session_ship_2026_05_17_core_network_redesign` + `project_archive_handoff_2026_05_17` memories

待处理:17 spec deltas × 8 capability spec.md merge → 7 `/opsx:archive` 调用(详 archive handoff memory,估 3.5-4h 专项 session)。`tools.runs.*` + `tools.ckpt.info` CLI 用法见 CLAUDE.md Build & Test 段。

## 当前 phase(2026-05-16)

**✅ doc 体系全量迁移 OpenSpec(P0 完 + P1 进行)+ v_phase2 / DMC infra 多线 ship**

### 1. 文档体系迁移 OpenSpec(2026-05-15/16,P0+P1 17 commits)

- **P0 完(8 commits)**:`openspec/` scaffold + `project.md` + 3 capability spec(`openspec-policy` / `engine-dsl` / `training-architecture`)+ `tools/_meta/check_openspec_indices.py` + pre-commit hooks 串接
- **P1 进行(9 commits)**:15 ADR 迁 `openspec/changes/archive/` + 8 capability spec(network/search-ismcts/search-parallel/engine-actions/dice/capi/runtime/env-config/eval-protocol)+ 5 paradigm dossier(`docs/paradigms/{az,bc,cfr,dmc,ppo}/`)+ 7 archived plan 迁 `5_history/`
- 旧 `docs/2_decisions/` 作 mirror 保留(ADR 实际权威在 `openspec/changes/archive/`);`docs/1_specs/` 仍在用,新内容写 `openspec/specs/`

### 2. v_phase2 真实卡 e2e 测试 + 支援区生命周期 ship(2026-05-15)

- **support zone lifecycle**(commit `62d641f` + `f8a8529` + `840b9c5` 等):`PlayerState.Supports` state / `MaxSupportSlots=4` / `HookSupportRemove` + `remove_support`/`count_support` builtin + `on_support_remove` DSL hook;6 区生命周期 spike test PASS
- **v_phase2 卡 e2e tests**(commit `c02bc88` 事件 3 卡 + `10ce0c9` 支援 2 卡 + `2fca63b` 装备 2 卡):7 case 覆盖事件/支援/装备真路径 + cleaned yaml ground truth 断言

### 3. DMC Phase 3.5 multi-process actor-learner ship(2026-05-13/14/15)

- **Phase 3.5 multi-process actor-learner**(commit `8cdd56c` DouZero pattern + `ce5049e` 合并 single/mp entry)
- **NaN/inf fail-fast guard**(`5ae3f7c`):dump batch+ckpt+diag 后 raise RuntimeError
- **`tools/eval` + `tools/runs` paradigm-agnostic refactor**(12 task 全 done,见 [`dmc_phase35_infra(archived)`](../5_history/dmc_phase35_infra.md))
- **41 项 DMC review critique 落盘**(2026-05-14,`docs/5_history/reviews/dmc_review.md`)

### 4. v_phase2 RL smoke + DSL v6 strict 仍 LIVE

- v_phase2 池(7 char / 6 卡)+ RL smoke s070 跑通(2026-05-12,commit `a0c26e9`)
- ADR-0019 DSL v6 strict 23 commits 链 2026-05-04~05-07 已落,Accepted de-facto;详 [`dsl_v6_progress.md`](dsl_v6_progress.md)
- v_phase2 deferred 机制 23 项仍 backlog(见 [`../3_plans/v_phase2_deferred.md`](../3_plans/v_phase2_deferred.md))

ADR-0011 pool versioning 仍然有效:`data/pools/{test_basic,v_legacy,v_phase2,spike}/`,manifest fold + 内存 cache。

---

## 已确定方向(2 条主线)

### A. 算法路线 — RL sweep 至 final verdict

| 数据点 | F1-D2 |
|---|---|
| Stage 3 1-card mirror baseline (s064-66, n=3) | 0.104 |
| Stage 3 1-card mirror + BC warm-start (r010-12, n=3) | 0.167 |
| Stage 3 1-card asymmetric (s068, n=3) | 0.271 ← +0.167 vs mirror |
| **s069 5× rollouts asymmetric (seed42 only, n=1)** | **0.5** ← 若 confirm 越过 stricter_pass |
| Production fallback BC alone (r009 ckpt) | 0.75 |

阶梯:s069 → s071 capacity → D2 NFSP / D3 deep CFR

### B. Infra 路线 — 正式版卡池准备

ADR-0011 落地了:
- 目录式版本(`data/pools/<id>/`)
- manifest.toml 描述 parent 链 + remove diff
- loader 沿链 fold + 整目录 override 语义
- pool resolution 走 process-global cache(脱耦磁盘)
- filler 字面量 hardcode 移除(Engine Ignorance 恢复)
- cfg 显式 deck_padding + pool 字段

下一步:渐进录入七圣召唤正式卡池(版本快照 + 平衡 patch)。已找到 `~/Documents/gicg_sim/data/raw/` 含 JSON 形式角色 / action 数据可作录入源。

---

## 主要困难(按严重度)

| # | 困难 | 严重度 | 缓解状态 |
|---|---|---|---|
| 1 | RL plateau 结构性(mirror Nash 锁) | 高 | s068 / s069 显示部分可破,sweep 中 |
| 2 | 数据基础窄(每 cfg n=3,std≈0.078) | 中 | multi-seed required,等 sweep 完整 |
| 3 | 正式卡池录入工作量(300+ 张 × 几十行 Lua) | 高 | infra ready;下一步:从 gicg_sim raw JSON 工具化转 Lua DSL |
| 4 | 旧 replay yaml 跨池引用 | 低 | 临时双池 union 兼容,长期重生成 |
| 5 | bit-exact baseline 兼容脆弱 | 中 | base preset 默认值集中管控 |
| 6 | pre-existing `seeds` field bug | 低 | test_shipped_configs 挂,与 ADR-0011 无关,后续单独 fix |

---

## 解决路径(按时间)

**~3.5h 内** — s069 跑完
- seed43/44 出齐 → s069 mean ± std
- F1-D2 ≥ 0.40 mean → closure 再被推翻,compute 是主因 → 推 production scale
- 0.27-0.39 之间 → s071 capacity probe(d_model 128→256, ~2h)

**1-2 天** — sweep cheap probe phase
- s071 跑完 → 进 / 出 algorithm probe
- capacity 也不行 → D2 NFSP / D3 deep CFR(2-3 周主线)
- 顺手 fix `seeds` field bug

**1-2 周(并行,与 RL sweep 解耦)** — 正式卡池 infra 验证
- 复制 `~/Documents/gicg_sim/` 工具到本仓库,拉取 raw JSON 数据
- 设计 JSON → Lua DSL 转换器(基于 raw schema 分析)
- 选第一个真实游戏版本(建议 v3.3 开服版,基础卡集最小)创建 `data/pools/v3.3/`
- 录 1-2 张真实卡走通端到端,验证 cfg `pool="v3.3"` 训练切换 work

**1-2 月** — 全量录入
- 主流版本(v3.3 → v4.5)所有卡 + 角色入 pool
- 训练 cfg 可 pin 单一版本 / 跨版本 ablation

---

## 上一里程碑

- **2026-05-15/16** OpenSpec 全量迁移 P0+P1 共 17 commits — scaffold + 11 capability spec + 15 ADR archive + 5 paradigm dossier + 7 plan archive (heads `9d8a4af`)
- **2026-05-15** v_phase2 卡 e2e tests ship — 事件/支援/装备 7 case 真路径 + cleaned yaml ground truth (commits `c02bc88` / `10ce0c9` / `2fca63b`)
- **2026-05-15** support zone lifecycle ship — `SlotSupport` state + 6 hooks + 6 区生命周期 spike test (commits `62d641f` / `f8a8529` / `840b9c5`)
- **2026-05-13/14** DMC Phase 3.5 multi-process actor-learner ship — DouZero pattern (commit `8cdd56c`),Phase 3.5 infra plan 12 task 全 done
- **2026-05-14** DMC review 41 项 critique 落盘 (`5_history/reviews/dmc_review.md`)
- **2026-05-12** v_phase2 真实角色 / 卡牌池建立 + RL smoke 跑通 (commits `c43a587` cleansing 链路重做 / `9969f2e` v_phase2 池 + spike test / `0f2a951` training pool_spec 修 / `d011859` smoke cfg)。详见 `../3_plans/v_phase2_deferred.md`
- **2026-04-28 PM** ADR-0011 落地:pool versioning + filler 引擎清理 + multi_seed resume + s069 重启 (commit `525296b`)
- **2026-04-28 PM** s068 D4 mirror-break probe F1-D2=0.271 (n=3),+0.167 vs mirror baseline,**部分推翻 closure**;reopen research(ADR-0010)
- **2026-04-28 AM** ADR-0009 paradigm pivot terminus — RL 三栈 × 5 stage 全失败(被 s068 部分推翻)
- **2026-04-28** r009 BC pretrain ep=3 ckpt vs F1-D2 = 0.75(production fallback)
- **2026-04-26** Stage 0-3 AZ pure self-play 完整 4-stage curriculum 双栈闭环
- **2026-04-25** Stage 1+2 BC→PPO PASS,multi-seed infra 落地
- **2026-04-24** RL paradigm pivot — pure end-to-end 路线证否

更长时间线: [`timeline.md`](timeline.md)

## 关键 link

### OpenSpec(P0/P1 落地后的新权威)
- 项目层 spec: [`openspec/project.md`](../../openspec/project.md) — SHALL invariants + 工具入口
- 活规约(capability spec): [`openspec/specs/`](../../openspec/specs/) — 11 capability(engine/search/network/training/env-config/eval-protocol/openspec-policy)
- 决策 archive: [`openspec/changes/archive/`](../../openspec/changes/archive/) — 15 ADR(0001-0019)

### Paradigm 科研复盘
- Paradigm landscape: [`docs/paradigms/README.md`](../paradigms/README.md) — 5 paradigm × verdict × 数据(AZ / BC / CFR / DMC / PPO)

### docs/ legacy 区(迁移中)
- 当前 shipped 代码状态: [`../1_specs/`](../1_specs/) (P1 迁移中,新内容在 `openspec/specs/`)
- 设计决策: [`../2_decisions/`](../2_decisions/) (已迁 `openspec/changes/archive/`,mirror 保留)
- 计划与 roadmap: [`../3_plans/`](../3_plans/) (active only;已实施/closed 移到 `5_history/`)
- 训练 run 注册: `python -m tools.runs.list` CLI(live);[`../5_history/runs_pre_redesign_2026_05_17.md`](../5_history/runs_pre_redesign_2026_05_17.md)(pre-redesign 2026-05-17 之前)
- 历史复盘 / archived plan: [`../5_history/`](../5_history/) — 新归档:`curriculum/` / `algorithm_sweep_2026_04_28.md` / `acceptance.md` / `az_plans/` + 3 个 implemented plan(`support_lifecycle_impl.md` / `v_phase2_cards_e2e_impl.md` / `dmc_phase35_infra.md`)
- 术语速查: [`glossary.md`](glossary.md)

## 编辑规则

- **本文件 LIVE**,phase 切换/里程碑达成 commit 内更新
- 顶部 `last_updated` 字段必须改
- 旧 phase status 沉淀到 `5_history/`,本文只反映当前
