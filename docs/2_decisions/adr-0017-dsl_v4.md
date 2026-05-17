---
adr: 0017
title: DSL v4 — RL-pipeline-rewrite enabled,30-axiom (含 prototype 实证修订)
status: PROPOSED (prototype Stage 1-10 全 PASS)
date: 2026-04-30 (last-rev 2026-05-01)
supersedes:
  - adr-0017-dsl_v2_generic_pipeline.md.v1-superseded (4-phase + Channel + helper 补丁化)
  - adr-0017-dsl_v2.md.v2-superseded (15 axiom 太少)
  - adr-0017-dsl_v3.md.v3-superseded (23 axiom 仍 3/20 ⛔ + 致命 closure 信息泄漏 + 跟 RL pipeline 不对齐)
prototype:
  - branch: feature/dsl-v4-prototype
  - location: gicg_engine/v2/ (~2640 LOC, 25 tests PASS, 9 source files + 11 test files)
  - 已验证 axiom: A1/A2/A2-rev/A4/A5/A11/A12/A13/A14/A16/A17/A19/A20/A21/A22(rewrite)/A24/A26/A27/A29/A30 + A31(新)
  - commits: f788abc (typed schema + L3 obs) + 3a6d236 (A16 owner-detach tombstone)
---

# ADR-0017 v4: DSL v4 — RL-pipeline-rewrite enabled

> **MOVED to `openspec/changes/archive/0017-dsl-v4/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0017-dsl-v4/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0017-dsl-v4/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


## Status

PROPOSED (prototype P0 验证通过)。user 已确认 3 个核心决策点 (2026-04-30):
- A24 cost payment auto-resolve (90% 卡 engine 自动选最小 dice 子集,RL 视角跳过 cost step)
- 全 ckpt 失效可接受,重训 Stage 0-3 baselines + r009 BC + r010 AZ-warmstart
- 允许破坏现有 RL pipeline (cgo schema / obs encoder / BC dataset / 重写)

**Prototype 实证 (gicg_engine/v2/, ~2640 LOC, 25 tests PASS — Stage 1-10 闭环)**:
- ✓ A11 forward-simulatable atomic step (Game.Clone bit-exact, 含 typed Items + LastTransitions)
- ✓ A2 propose-resolve-commit + **A2-rev source_hook_id 整组 reject** (TestSourceHookGroupReject + TestBoostNotConsumedWhenFullyAbsorbed 旧 KNOWN ISSUE 转真断言 PASS)
- ✓ **A30 PDR-sync-with-hold 解 #10 勘探钻机 fundamental flaw** (TestPDRSyncWithHold_KantanDrillScenario, hp 10→8 / hand 减 1 / solidarity +1)
- ✓ **A22 ctx 字段 filter 取代旧 silent_kind 白名单** (TestA22TriggerSourceFilter, 4 场景: player+fire / equip / reaction / non-fire; engine 不再维护 silent.lua)
- ✓ **A16 owner-detach hook lifecycle (tombstone GC)** (TestA16OwnerDetachHook + CollectionOwnerDetach + DestroyRollback, PropDestroy proposal kind)
- ✓ A24 cost auto-resolve O(N) (4 test, 100k iter no NP blowup)
- ✓ A26 multi-instance substate + recycle pool (2 test)
- ✓ A19 plain_key_fn typed dispatch (取代旧 closure plain-data view)
- ✓ A14 ownership-bound mask + SwapCollections
- ✓ A17/A29 form-bound hook auto-skip + skill_set replace
- ✓ A13 reward attribution at commit (rollback 不累加)
- ✓ A12 perf microbench: 1k Clone + 1k FireSubAction
- ✓ E2E 反应链综合 (火+水→蒸发+万叶 boost = 5 dmg)
- ✓ **A31 L3 obs typed transition log** (TestL3ObsLastTransitions, ring buffer bounded 16, RL 可唯一推理 last K 步因果)

**全 typed schema 落地** (no `any`, no `map[string]any`, no mock, no placeholder):
- Item interface + 3 concrete (CardRef/SummonRef/SkillRef) all real schema
- 10 个 typed enum (ElementType / CardKind / SubActionKind / TriggerSource /
  DiceColor / FormStateKind / HookPhase / DecisionKind / SubstateActionKind / ItemKind)
- DecisionSpec / DecisionResult typed sum
- SubstateInitData / SubstateExitData typed union struct
- MarkerRef declared marker (取代 marker name 字符串)

## Context

### v1 → v2 → v3 → v4 历程

- v1 (current): 24 typed hookType + 自动扣 dice + engine 硬编 game rules,18 张代表卡 1 张干净覆盖
- v2 (1.0,补丁化): 4-phase + Channel + helper,reviewer 22 项问题,user 否决
- v2 (2.0,15 axiom): 11/20 卡 ⛔
- v3 (23 axiom): 8/20 干净 (改善),3 张 ⛔ + 致命 closure 信息泄漏 (A19) + 跟 RL pipeline 不对齐 (cgo/obs/ckpt 全废没 plan)
- v4 (28 axiom): 6 axiom 修订 + 6 axiom 新增 + RL pipeline migration spec
- **v4 prototype (本 ADR rev)**: 745 LOC prototype 实证 + A2 修订加 source_hook_id + A30 新增 PDR-sync-with-hold,合计 30 axiom (A1-A30)

## v4 关键调整 (基于 v3 三轮 review 致命问题)

### 修订 axiom

| Axiom | v3 → v4 (含 prototype rev) |
|---|---|
| **A1 + A20** | 承认 state container **两种 mutation kind**: 常规 container 走 A2 propose-commit; substate state 走"私有 mutation" (direct setter, 无 hook fire)。两者隔离,A1 不再说"无第三类",改"两类 mutation 协议" |
| **A2 prototype rev** | propose-resolve-commit-rollback;嵌套 SubAction 单一原子事务;**proposal 自动携带 source_hook_id;reject 时按 source_hook_id 整组 reject** (engine 自动检测同源 group,任一 reject → 整组 reject)。解 v3 review #5 "boost 被全抵不返还" / "护盾全抵后 charge 仍消耗" 类问题。prototype `TestBoostNotConsumedWhenFullyAbsorbed` known issue 来源 |
| **A6'** | propose hook 内**允许** trigger substate (走 A25 async 或 A30 sync);任何 PDR 触发后 engine 处理 |
| **A12** | 性能目标具体化: Phase 0 强制 microbench prototype, **单 Game.Step ≤2× v1 wall / single Clone ≤1.5× v1 byte**; prototype 不达标停 Phase 0 重设计 |
| **A13** | per-proposal owner 保留, **buff_source 字段 RL 不消费** (memory `feedback_no_ids` consistent), 只用于 replay analytics + 卡作者 debug。RL reward 仍按 player-level |
| **A14 + A19** | hidden_from 改 **ownership-bound** (跟随容器 owner 自动决定, owner 变 → mask 自动翻); A19 closure **限定 plain-data view** — engine 构建 masked plain copy 给 closure, closure 不能 capture 外部 mutable ref。解 #5 closure 信息泄漏 + #15 跨方 swap |
| **A21** | provenance 链 **bound max 32 entries**, 超 → drop oldest 加 marker (避免 unbounded clone) |
| **A22 prototype rewrite** | ~~silent_skip_hooks 按 silent_kind 分桶 4 类白名单~~ → engine 只塞 typed `ctx.TriggerSource` enum (7 类: PlayerAction / EquipOnPlay / Specialty / ReactionSubdamage / SummonAutoAction / CardSubAction / EngineInternal) + `ctx.IsPlayerAction()` 便利方法。业务 hook 自 filter (例 `if !ctx.IsPlayerAction() { return }`)。engine 不维护任何 silent 白名单 — 跟 A4 dependency / A29 active_in_form 同模式。删除 `data/system/silent.lua` (~50 LOC) + hook opts `silent_kind_skip` 字段。验证: `TestA22TriggerSourceFilter` PASS (烟绯 charge: player+fire→+2, equip/reaction/non-fire→0)。**对齐 A10 engine 最小化** |
| **A25 prototype rev** | 拆 **A25-async** (原版): propose hook mark, hook chain 完 + 主 transaction commit 后 engine FIFO 处理 substate, completion **不能改 in-flight proposal** (适用纯展示 / 无后续逻辑);完整 PDR 协议见 A30 |

### 新增 axiom

| Axiom | 解决 |
|---|---|
| **A24 — Cost payment auto-resolve** | engine 默认按"字典序最小合法 dice 子集"自动 pay; 只在 cost 有 meaningful choice (例同色 vs 万能 / 多种合法支付组合且玩家可能 strategically 选不同) 时显式 enter cost_payment substate。**90% 普通卡跳过 RL cost payment step**, 避免 expand_union_k 重蹈覆辙 |
| **A25 — PDR-async** (见上 prototype rev) | propose hook mark, transaction commit 后处理 substate, completion 不能改 in-flight proposal |
| **A26 — Multi-instance substate** | declare_substate 是 template, enter_substate 时**实例化新 state container set** (每实例独立 declared); 多 instance 并存时各自隔离 + 自动 GC on exit。解 #16 一掷乾坤 multi-instance |
| **A27 — Card/Summon instance lifecycle** | declare_collection 显式 `item_ownership = instance \| shared`: instance 时每 insert 创建新独立 instance (有自己的 attached_hooks / state); shared 时 ref 共享。card/summon 默认 instance, dice 默认 shared。解 #6 #18 实例化语义 |
| **A28 — Hierarchical obs encoding** | AZ obs encoder **不 union 全部 substate schema**: base game obs + 当前 active substate 的 state encoding (动态切换); no-substate 时 substate 部分 zero。解 #9 obs schema union 不可学 (零空间问题不加剧, memory `project_cross_attn_saturation`) |
| **A29 — Attached entity first-class** | declare_card opts 加 `attached_to_char = ref?` (装备绑角色), engine 框架管 attached state + lifecycle; form-bound hooks 可声明 `active_in_form = ...` engine 自动 fire/skip。解 #3 #4 #9 #12 attached_char + form-bound hook 切换 |
| **A30 — PDR-sync-with-hold** (prototype 实证) | 任何 phase 的 hook 调 `ctx.RequestDecisionSync(spec)` → engine **abort hook chain 当前位置 + 暴露 HeldCtx 给 RL agent** (新 game step,plain-data 可 fork 兼容 A11);agent 选完后写 `HeldCtx.DecisionResult` → `engine.ResumeHeldCtx()` 从 abort 点继续 hook chain → 后续 resolve hook 可读 ctx.DecisionResult 改 in-flight proposal → 同 transaction 真 commit。**跨多 RL step 但 transaction atomic**。验证: `gicg_engine/v2/v2_test.go::TestPDRSyncWithHold_KantanDrillScenario` PASS。覆盖 ~15-20 张受伤被动决策卡 (勘探钻机 / 苦痛奉还 / 安柏兔兔伯爵 / etc.)。**解 v3/v4 review fundamental flaw #10** |

---

## Axiom 集合 (31 条 完整列表 — 含 prototype 修订)

### 基础架构 (A1-A9)

- **A1** State 统一容器: scalar (counter) + collection (slice of plain object) + substate state container (private mutation kind)
- **A2** 常规 mutation = propose-resolve-commit-rollback 事务; 嵌套 SubAction 单一原子事务 (子 commit 是父一部分)
- **A3** 无 Channel: hook filter 通过 (container, op, source, payload) 四元组
- **A4** Hook 顺序 = declared dependency: name 全局 unique + after/before/replace + topological sort + lazy resolve + 错误 trace 到 file:line
- **A5** 三层 pipeline (Action / SubAction / Mutation), ctx 嵌套深度上限 64 + abort 标 illegal state
- **A6'** Effect atomic + multi-step substate (统一所有 player decision); propose hook 内可 PDR (A25)
- **A7'** Reaction = SubAction.deal_damage 的 propose hook (无独立 declare_reaction API)
- **A8** Layer 2 helper 不在 engine, helper 注册必须 user 显式 pass name
- **A9** 严格 single stack, breaking change, 无 alias / shim / transitional adapter

### Engine 框架 (A10):

- **A10** Engine 框架最小化, 16 项基础设施:
  1. Game.Step(action) → Game' protocol
  2. Container 三类原语 (scalar / collection / substate)
  3. Pipeline 三层 dispatcher
  4. RNG seed 管理 (deterministic per Game.Step, RNG seed = hash(state, step_counter))
  5. Hidden 容器 mask 实现 + ownership-bound 自动翻 (A14)
  6. Coroutine-free atomic step 强制
  7. Game.Clone 深拷贝
  8. obs encoder 框架 (hierarchical, A28)
  9. Game.LegalActions (pure function)
  10. RewardAccum 框架 (commit 后 player-level 累加, A13)
  11. Hook lifecycle 框架 (注册/owner-bind/auto-detach, A16)
  12. Form / SkillSet 容器原语 + active_in_form filter (A17 + A29)
  13. Target-spec 协议 (A18)
  14. Hidden 容器 server-side select/sort/aggregate + closure plain-data view (A19)
  15. **PDR 队列 + substate enter/exit** (A25 + A26)
  16. **Cost payment auto-resolve framework** (A24)

### RL 可感知 (A11-A14):

- **A11** Forward-simulatable atomic step (substate state 用 declared container 自动覆盖)
- **A12** Action 枚举 pure function, perf 目标 ≤2× v1 wall + ≤1.5× v1 clone byte; Phase 0 microbench 强制
- **A13** Reward commit 后 player-level 累加 (buff_source 字段不进 RL reward, 仅 analytics)
- **A14** Hidden info ownership-bound 显式; closure 限 plain-data view

### 修饰能力 (A15):

- **A15** Modifications first-class: declared rule 可被其他 declared hook 修饰 (新增/替代/取消) + name 是 stable API

### 新增 first-class 概念 (A16-A31):

- **A16** (prototype 实证) Hook lifecycle owner-bind + tombstone GC: Scalar/Collection 加 Destroyed bool, propose `PropDestroy` proposal kind, hookOwnerAlive() 检查 OwnerScalar.Destroyed / OwnerCol.Destroyed → 自动 detach。transactional (rollback 时 Destroyed 还原)。验证: `TestA16OwnerDetachHook` (装备 durability 2→1→0+destroy → 第三击 hook detach) + `TestA16CollectionOwnerDetach` (support zone destroy 后 hook detach) + `TestA16DestroyRollback` (整 transaction 回滚时 Destroyed 也回滚)
- **A17** Form / SkillSet 替换 = collection_replace
- **A18** Player decision via substate (含 cost payment + target + 挑选)
- **A19** Hidden 容器 server-side resolve + closure plain-data view
- **A20** Substate state first-class declared (private mutation kind, A1 一致)
- **A21** Provenance chain (max 32 entries, 超 drop oldest)
- **A22** (prototype rewrite) ctx.TriggerSource enum + IsPlayerAction() — 业务 hook 自 filter, engine 不维护白名单 (取代旧 silent_kind 分桶方案)
- **A23** Engine stdlib whitelist (math.* / string.* / table.* / pairs / ipairs 等)
- **A24** Cost payment auto-resolve (90% 卡跳过 RL cost step)
- **A25** (prototype 修订 → A25-async + A30-sync 二变体并存) Player Decision Request 协议 — async 变体: propose hook 内 mark, hook chain 完 + 主 transaction commit 后 engine FIFO 处理 substate, completion 不能改 in-flight proposal (适用纯展示 / 无后续逻辑场景)
- **A26** Multi-instance substate (template + 实例化 state container set)
- **A27** Card/summon/dice instance lifecycle (item_ownership=instance|shared)
- **A28** Hierarchical obs encoding (base + active substate, no union)
- **A29** Attached entity first-class (declare_card opts attached_to_char + active_in_form)
- **A30** (prototype 实证 — 解 #10 fundamental flaw) **PDR-sync-with-hold**: 任何 phase 的 hook 调 `ctx.RequestDecisionSync(spec)` → engine **abort hook chain 当前位置 + 暴露 HeldCtx 给 RL agent** (新 game step,plain-data 可 fork 兼容 A11);agent 选完后写 `HeldCtx.DecisionResult` → `engine.ResumeHeldCtx()` 从 abort 点继续 hook chain → 后续 resolve hook 可读 ctx.DecisionResult 改 in-flight proposal → 同 transaction 真 commit。**跨多 RL step 但 transaction atomic**。验证: `gicg_engine/v2/v2_test.go::TestPDRSyncWithHold_KantanDrillScenario` PASS (hp 10→8 / hand 减 1 / solidarity +1)。覆盖 ~15-20 张 #10 类受伤被动决策卡 (勘探钻机 / 苦痛奉还 / 安柏兔兔伯爵 / etc.)
- **A31** (prototype 实证, 新增) **L3 obs typed transition log**: 每 SubAction commit 后 engine append 一个 `TransitionEntry { SubAction, Actor, Target, Element, TriggerSource, Value, Cancelled }` 到 `Game.LastTransitions` ring (bounded 16, 超 → drop oldest, 与 A21 provenance 一致 bound)。RL obs encoder 把 LastTransitions encode 成 fixed-shape tensor (16 × 7 typed fields)。**让 RL 可从 obs 唯一推理 last K 步因果** (而不只学行为后效)。这跟 ctx 黑盒不矛盾 — transient transaction state 仍不进 obs, 但 commit 后的 typed snapshot 进。验证: `TestL3ObsLastTransitions` PASS (3 dmg 后 20 heal 验证 ring drop oldest)。**对应 user 硬约束: 除最基础规则, 其他状态应可被 obs 唯一推理**

---

## Layer 1 — primitive 完整设计

### Container 三类

```lua
-- 标量 (counter)
local hp = declare_scalar(name, opts)
-- opts: { init, min, max, tag, owner=(p,c)?, hidden_from_owner_of=(p,-1)?, ref_kind }

-- 集合 (region)
local hand = declare_collection(name, opts)
-- opts: { item_type, max_size, owner=(p,-1)?, hidden_from_owner_of=(p,-1)?,
--          item_ownership="instance"|"shared", sort_key=fn? }

-- 子状态机 template
declare_substate(name, {
  state_template = {
    field_a = scalar_template({ init=2 }),       -- 不是 declared scalar,是 template
    field_b = collection_template({ ... }),
  },
  legal_actions = function(state_inst) → list<Action>,
  on_action     = function(state_inst, action),
})

-- enter substate: engine 实例化 state_template → state_inst (其中每 field 是真 declared container)
enter_substate(name, init_data?)  -- (in propose hook 内 → 进 PDR 队列, A25)
```

### Pipeline 三层 + Phase

| 层 | 触发 | Phase 顺序 |
|---|---|---|
| Action | 玩家选 (skill_use / card_play / switch / end_turn / substate_action / cost_payment_action) | propose → resolve → commit (drain PDR queue → enter pending substates as new atomic steps) → on_after |
| SubAction | Action 内子行为 (deal_damage / heal / draw / discard / dice_op / aura_change / summon_create / form_change) | propose → resolve → commit → rollback? |
| Mutation | 单容器修改 (scalar +=N / collection insert/remove/replace) | propose → resolve → commit (engine atomic apply) → on_after |

### Hook 注册

```lua
on_propose(scope, opts, fn)
on_resolve(scope, opts, fn)
on_commit (scope, opts, fn)
on_rollback(scope, opts, fn)

scope:
  Container.Match(c) / Container.Tag(t)
  SubAction.Match(deal_damage) / SubAction.Match(any)
  Action.Match(skill_use) / Action.Match(any)

opts (强制 name + owner + 显式 dependency):
{
  name              = "owner_qualifier/purpose",   -- 全局 unique
  owner             = my_card_ref,                  -- A16 lifetime
  after             = { "reaction/swirl" },         -- A4 dependency
  before            = { "death_check" },
  replace           = { "old_rule_name" },          -- A15 取代
  active_in_form    = "normal" | nil,               -- A29 form-bound auto fire/skip
  -- A22 删除: 不再有 silent_kind_skip; 业务 hook 改读 ctx.TriggerSource / ctx.IsPlayerAction()
  legal_dynamic     = false,                        -- A12 是否影响 legal_actions
}
```

### Proposal 数据结构

```
{
  kind        : "value_delta" | "value_set" | "collection_insert" | "collection_remove" | "collection_replace" | "marker" | "request_decision"
  target      : container ref
  delta / item / position / payload : kind-specific
  owner       : (player, char, buff_source)        -- A13 reward attribution (不进 RL reward)
  provenance  : [(hook_name, kind, parent_id?)]    -- A21 自动填, max 32 entries
  source_hook : current hook name (自动)
  rejected    : bool                                -- resolve phase 设
}
```

### PDR 协议 (A25)

```lua
-- 任何 hook 内可调:
ctx.request_decision({
  substate_name = "select_discard_for_block",
  init_data     = { hand_player=ctx.target_player, max_discard=1 },
  on_complete   = function(result) ... end,        -- 选完后 callback
})
-- mark 入 ctx.pending_decisions[],hook 继续跑
-- hook chain 跑完 + 主 transaction commit 后,engine FIFO 处理 PDR:
--   1. enter_substate(spec.substate_name, spec.init_data) 作为新 atomic step
--   2. RL agent 在新 step 选 substate.legal_actions 之一
--   3. substate exit 时 engine 跑 spec.on_complete(result)
--   4. 处理下一 PDR
```

### Cost payment auto-resolve (A24)

```lua
-- 普通卡 cost = { 火: 1, 无色: 2 }
-- engine 默认:
--   1. 计算合法 dice 子集列表
--   2. 按 (字典序最小 specific elements + omni 优先)排序
--   3. 自动选第一个 → 扣 dice
-- 不进 RL substate

-- 有 meaningful choice 的 case:
--   - 多种合法子集且 cost spec 含 'same' (同色, 玩家可能 strategically 选不同色)
--   - 元素共鸣 cost 与万能选择
-- engine 检测后 enter cost_payment substate (RL 选)

-- 卡作者可 override:
declare_card "X" { cost={...}, force_cost_substate=true, ... }
```

### Hidden + closure plain-data view (A19)

```lua
-- DSL 调用 (engine server-side resolve):
local target_card_ref = enemy_hand:select_max(plain_key_fn("cost_total"))
-- plain_key_fn(field_name) → engine 内置 key fn,只能读 plain field name
-- 不允许 user-defined arbitrary closure 作为 key_fn

-- 操作结果 (哪个 ref 被选 + 移动后位置变化) 对所有玩家公开
ctx.propose({ kind="collection_remove", target=enemy_hand, item=target_card_ref })
ctx.propose({ kind="collection_insert", target=enemy_deck, item=target_card_ref, position="bottom" })

-- IS-MCTS determinize 时, server-side select 用同 RNG seed (基于 game state hash) 重现一致
```

### Reaction (system DSL,A7' 一致)

```lua
on_propose(SubAction.Match(deal_damage), {
  name  = "reaction/vaporize",
  owner = system_owner_ref,    -- system_owner 是引擎 declared 的全局 system ref (lifetime = game)
}, function(ctx)
  if not vaporize_match(ctx.element, target_aura_of(ctx.target)) then return end
  ctx.propose({ kind="value_delta", target=ctx.value_proposal, delta=+2, owner=system_attribution(ctx) })
  ctx.propose({ kind="value_set", target=ctx.element_field, to=Element.None })
  ctx.propose({ kind="collection_remove", target=aura_of(ctx.target), item=target_aura })
  ctx.propose({ kind="marker", payload={ reaction_kind="vaporize" } })
end)
```

---

## v1 → v4 hook 映射 (摘要)

`on_damage_boost / reduce` → `on_resolve(SubAction.Match(deal_damage), ...)` (attacker 视角注 Action 层) /
`on_reaction_damage` → system/reactions/*.lua propose hook /
`on_after_damage` → `on_commit(SubAction.Match(deal_damage))` /
`on_before/after_heal/energy_*/write` → `on_propose/resolve/commit` 对应 scope /
`register_on_tag_write` → `on_propose(Container.Tag)` /
`on_action_check / prepare` → Action.Match propose / resolve /
`on_skill_use / card_play / switch` → Action.Match commit /
`on_round_* / on_death/revive` → system DSL declared /
`cost_mod / cost_total / was_applied` → 删除, cost discount = ActionPipeline propose hook /
v1 自动扣 dice → A24 auto-resolve + A18 substate (有 meaningful choice 时)

---

## Migration Plan + LOC 估算

### Phase 0 — engine 框架重写

新文件:
- `gicg_engine/container.go` (~+800): scalar / collection / substate 三类 + ownership-bound mask
- `gicg_engine/pipeline.go` (~+1200): Action / SubAction / Mutation 三层 dispatcher + propose-resolve-commit-rollback + PDR 队列
- `gicg_engine/transaction.go` (~+400): proposal 数据结构 + commit atomic apply / rollback
- `gicg_engine/lifecycle.go` (~+300): hook owner-bind + auto-detach
- `gicg_engine/cost_payment.go` (~+400): A24 auto-resolve framework + meaningful-choice 检测
- `gicg_engine/substate.go` (~+500): template + 实例化 state container set + multi-instance
- `gicg_engine/interp/proxies_hidden.go` (~+200): closure plain-data view + plain_key_fn 内置

修改:
- `gicg_engine/damage.go` (~+150 / ~-300): 移 4-phase fire 出, 改 deal_damage 内部 + death check 移到 system DSL
- `gicg_engine/context.go` (~+250 / ~-50): EventContext v4 字段 (proposals / pending_decisions / provenance / is_specialty / silent_kind / etc.)
- `gicg_engine/game.go` (~+200 / ~-150): Game struct + Clone + Step + LegalActions
- `gicg_engine/interp/builtins*.go` (~+800 / ~-1500): 重写所有 builtin 适配新 phase API + 删 v1 24 hookType 注册 + cost_mod 三件套

删除:
- `gicg_engine/hook.go` 旧 HookType enum (~-200): 12 typed hookType 全删
- v1 cost_mod / was_applied 相关 (~-200)

合计: **新增 ~3800 LOC + 修改 ~1400 / 删 ~2150**

### Phase 1 — system DSL 重写

按依赖序新写:
- `data/system/aura.lua` (~+150): 元素附着规则 declared
- `data/system/reactions/*.lua` (8 文件 × ~80 = ~+640): 按 A7' 重写
- `data/system/death.lua` (~+80): 从 engine 挪出
- `data/system/energy.lua` (~+200): 能量获得规则 declared
- `data/system/switch.lua` (~+100)
- `data/system/draw.lua` / `dice_roll.lua` / `round.lua` (~+300 合计)
- `data/system/preparing.lua` (~+150)
- `data/system/specialty.lua` (~+100)
- ~~`data/system/silent.lua` (~+50)~~: A22 prototype rewrite 后不再需要,业务 hook 自读 ctx.TriggerSource
- `data/system/food.lua` / `equip.lua` / `frozen.lua` / `timeout.lua` / `alive.lua` (~+400 合计)
- `data/lib/{buff,shield,aura,charge_pool,passive}.lua` (~+500 合计): helper, 按 v_legacy 重写需求 incrementally

重写:
- `data/pools/v_legacy/cards/*.lua` (7 张 × ~50-100 = ~+500 / ~-300 旧版): 全按 v4 重写

合计: **新增 ~3600 LOC + 改 / 删 v_legacy ~800**

### Phase 1.5 — RL pipeline migration (v4 新加)

新文件 / 改:
- `gicg_engine/capi/*.go` (~+400 / ~-200): cgo struct schema 改 (含 substate / pending_decisions / per-proposal owner / etc.)
- `gicg_env/engine.py` (~+200 / ~-150): Python ctypes binding 改适配
- `gicg_env/_obs.py` (~+800 / ~-400): obs encoder 重写, hierarchical encoding (A28)
- `training/framework/step_encoding.py` (~+300 / ~-200): action enum 重写 (含 substate kind / cost_payment auto vs explicit)
- `training/az/bc_train.py` + `tools/gen_bc_dataset_az.py` (~+200 / ~-100): BC dataset 生成器适配新 schema
- 删除:`artifacts/checkpoints/*` 全部 (~删除 ~5GB; LOC=N/A)

合计: **新增 ~1900 LOC + 改 ~1050 + 全 ckpt 删除**

### Phase 2 — 验证 + retrain

- `gicg_engine/tests/*.go` 改 + 新加 (~+800 / ~-400): 含 prepare_skill / specialty / e2e / mirror match / 反应链 / multi-step substate / PDR
- `training/tests/*.py` (~+400 / ~-200): 适配新 obs / action schema
- golden replay diff 工具 (~+300): v1 v2 同 seed 同 action 序列必 game state bit-exact (允许 log format 差)
- perf microbench 脚本 (~+200): Game.Step / Clone / LegalActions wall + byte
- BC dataset 重生成: 5GB 数据, LOC=N/A
- Retrain Stage 0-3 baselines (n=3 each): 12 runs × `tools.gen_bc_dataset_az` + `training.az.bc_train` + RL gauntlet

合计: **新增 ~1700 LOC + 改 ~600**

### Phase 3 — cleanup

- 删 v1 24 hookType enum 残余 (~-100)
- 删 cost_mod / tx_consume 等过渡名 (~-50)
- 改 `docs/1_specs/engine/dsl/api.md` (~+400 / ~-300): v4 API reference
- 改 `CLAUDE.md` Engine Ignorance 章节 (~+50 / ~-30)

合计: **改 ~750**

### 总 LOC 估算

| Phase | 新增 | 修改 | 删除 |
|---|---|---|---|
| Phase 0 engine | ~3800 | ~1400 | ~2150 |
| Phase 1 system DSL | ~3600 | — | ~800 (v_legacy 旧版) |
| Phase 1.5 RL pipeline | ~1900 | ~1050 | (全 ckpt) |
| Phase 2 验证 + retrain | ~1700 | ~600 | — |
| Phase 3 cleanup | — | ~750 | ~150 |
| **合计** | **~11000 新增** | **~3800 修改** | **~3100 删除** + 全 ckpt |

---

## Risks

### R1 — A24 cost auto-resolve "meaningful choice" 检测算法
"是否有 strategic 价值" 是 game-design 判断。简单实现:cost spec 含 `same` 元素 OR 有 ≥2 种合法子集差异 ≥ 1 element kind → 显式 substate;否则 auto。但**月桂宝冠 cost discount 后** "原本无 choice" 可能变 "有 choice",检测逻辑需考虑 cost discount 后的 effective cost。算法实现 ~+200 LOC, 测试覆盖 ~+150 LOC

### R2 — A25 PDR FIFO 跨多 hook 顺序
hook chain 中 hook A 调 PDR(decision_X), hook B 调 PDR(decision_Y),hook chain 跑完后 engine FIFO 处理 X → Y。但若 A B 是同 propose phase 不同 hook,FIFO 顺序按 hook chain 执行序 = topological sort 决定。**多 PDR 场景测试覆盖** Phase 0 microbench 必须含。

### R3 — A26 multi-instance substate 性能
template + enter 时实例化 state container set,**每实例独立 declared** = 每 enter 跑一次 declare_scalar/collection 序列。重投/挑选高频卡 一局可能 enter 10+ 次 → declare 开销累积。实施细节: 用 pool/recycle 机制 (exit 时不真删,标 free, 下次 enter 复用),~+150 LOC pool 实现。

### R4 — A28 hierarchical obs encoding 与 RL policy head 维度
base obs + 当前 active substate state encoding。policy head 输出维度 = base action enum + 当前 substate legal_actions 最大值 padding。**legal_actions 在 substate 内是动态枚举**,policy head 维度按全局 max(legal_actions across all substate kind) 设。实施细节: ~+300 LOC obs encoder + policy head 适配。

### R5 — Retrain wall time 估算 (LOC 视角)
retrain 不是 LOC, 但 BC dataset gen + Stage 0-3 multi-seed retrain 是产物。estimated runs:
- gen_bc_dataset_az × 1: ~300s
- bc_train × 1: ~125s
- AZ Stage 0 baseline × 3 seeds: 3 × ~22min = ~66min
- AZ Stage 1 baseline × 3 seeds: 3 × ~22min = ~66min
- AZ Stage 2 baseline × 3 seeds: 3 × ~22min = ~66min
- AZ Stage 3 1-card baseline × 3 seeds: 3 × ~22min = ~66min
- gauntlet eval × 12 ckpt: 12 × ~90s = ~18min
- **合计 GPU/wall ~5h** (host-native; container 慢 1.5×)

### R6 — Phase 0 perf prototype 不达标
A12 强制 Phase 0 microbench prototype, 不达标停 Phase 0 重设计。fallback path: 若 Game.Step > 2× v1 → 检查 hook chain dispatch 是否可优化 (cache topological sort 结果 / proposal struct alloc 池化 / etc.); 若 Clone > 1.5× v1 byte → 检查 substate state recycle / provenance bound / etc.

### R7 — closure plain_key_fn 限制是否够表达
A19 限定 closure 不能 capture 外部 mutable, 只能用 engine 内置 plain_key_fn("field_name") 等基础组合。某些卡可能需 multi-field 复合 sort key (例 "cost 最高且数字最小")。fallback: engine 内置 composite_key_fn(["cost", "id"]) 等 builder, ~+150 LOC builder 实现。

---

## 不在本 ADR 范围

下列由 v4 axiom 自然支持:
- 始基反应 (declare_reaction-style 普通 propose hook + arche element first-class)
- on_battle_start (system DSL `on_propose(Action.Match(battle_start))`)
- find_char (collection container iter + filter,DSL 写)
- 数学 builtin (A23 stdlib whitelist)
- 跨方手牌 / 牌组 swap (A14 ownership-bound + A19 server-side resolve)
- form-swap 替换 hooks (A29 active_in_form filter)
- player decision 内嵌 propose hook (A25 PDR)

下列需 follow-up ADR (v4 不阻塞):
- detailed engine schema (Container struct / proposal dataclass / pipeline ctx 字段表)
- helper lib API 稳定后的 reference doc
- substate body lint 规则 (R3 缓解)
- A24 meaningful-choice 检测算法详细 spec

---

## 接下来

1. user 批准本 v4 ADR (PROPOSED → ACCEPTED)
2. fire 4 轮 review (架构 + 表达力 + RL pipeline + 实施细节 perf+migration)
3. iterate 1-2 cycle 修 axiom / 设计
4. 通过后进 Phase 0 engine 改, microbench prototype 强制 ≤2× v1 wall + ≤1.5× v1 clone byte
