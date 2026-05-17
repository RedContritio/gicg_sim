# Design (retrospective)

## Consequences

### v4 关键修订 axiom

| Axiom | v3 → v4 (含 prototype rev) |
|---|---|
| A1 + A20 | 承认 state container 两种 mutation kind:常规 container 走 A2 propose-commit;substate state 走"私有 mutation" (direct setter,无 hook fire)。两者隔离 |
| A2 prototype rev | propose-resolve-commit-rollback;嵌套 SubAction 单一原子事务;proposal 自动携带 source_hook_id;reject 时按 source_hook_id 整组 reject(engine 自动检测同源 group) |
| A6' | propose hook 内允许 trigger substate (走 A25 async 或 A30 sync) |
| A12 | 性能目标具体化:Phase 0 强制 microbench prototype, 单 Game.Step ≤2× v1 wall / single Clone ≤1.5× v1 byte;prototype 不达标停 Phase 0 重设计 |
| A13 | per-proposal owner 保留,buff_source 字段 RL 不消费,只用于 replay analytics + 卡作者 debug。RL reward 仍按 player-level |
| A14 + A19 | hidden_from 改 ownership-bound(跟随容器 owner 自动决定);A19 closure 限定 plain-data view |
| A21 | provenance 链 bound max 32 entries,超 → drop oldest 加 marker |
| A22 prototype rewrite | ctx.TriggerSource enum 7 类 + IsPlayerAction() 便利方法;业务 hook 自 filter。engine 不维护任何 silent 白名单 |
| A25 prototype rev | 拆 A25-async(原版):propose hook mark,hook chain 完 + 主 transaction commit 后 engine FIFO 处理 substate,completion 不能改 in-flight proposal |

### 新增 axiom

| Axiom | 解决 |
|---|---|
| A24 Cost payment auto-resolve | engine 默认字典序最小合法 dice 子集自动 pay;只在有 meaningful choice 时显式 enter cost_payment substate。90% 普通卡跳过 RL cost payment step |
| A25 PDR-async | propose hook mark,transaction commit 后处理 substate |
| A26 Multi-instance substate | declare_substate template,enter 时实例化新 state container set,多 instance 并存自动 GC |
| A27 Card/Summon instance lifecycle | declare_collection 显式 `item_ownership = instance \| shared`;card/summon 默认 instance,dice 默认 shared |
| A28 Hierarchical obs encoding | AZ obs encoder 不 union 全部 substate schema:base game obs + 当前 active substate state encoding;no-substate 时 substate 部分 zero |
| A29 Attached entity first-class | declare_card opts 加 `attached_to_char = ref?`;form-bound hooks 可声明 `active_in_form = ...` |
| A30 PDR-sync-with-hold (prototype 实证) | 任何 phase 的 hook 调 `ctx.RequestDecisionSync(spec)` → engine abort hook chain 当前位置 + 暴露 HeldCtx 给 RL agent (新 game step);agent 选完后写 `HeldCtx.DecisionResult` → `engine.ResumeHeldCtx()` 从 abort 点继续 → 后续 resolve hook 可读 ctx.DecisionResult 改 in-flight proposal → 同 transaction 真 commit。跨多 RL step 但 transaction atomic |
| A31 L3 obs typed transition log | 每 SubAction commit 后 engine append TransitionEntry 到 `Game.LastTransitions` ring (bounded 16, 与 A21 一致 bound)。RL 可从 obs 唯一推理 last K 步因果 |

### DSL v2/v3 historical iterations

ADR-0017 经过 v1→v2→v3→v4 迭代,v4 为最终采纳版本。v1-v3 快照见 git history(commit 之前文件:
`docs/2_decisions/adr-0017-dsl_v2*.md.v{1,2,3}-superseded`,P1-T1 删除)。

## Tradeoffs revisited

### Risks

- **R1** A24 cost auto-resolve "meaningful choice" 检测:cost spec 含 `same` 元素 OR 有 ≥2 种合法
  子集差异 ≥ 1 element kind → 显式 substate;但月桂宝冠 cost discount 后可能变化,需考虑 effective
  cost。算法 ~+200 LOC + 测试 ~+150 LOC
- **R2** A25 PDR FIFO 跨多 hook 顺序:FIFO 顺序按 hook chain 执行序 = topological sort;多 PDR 场景
  测试覆盖 Phase 0 microbench 必须含
- **R3** A26 multi-instance substate 性能:每 enter 跑一次 declare 序列;高频卡一局 enter 10+ 次。
  pool/recycle 机制(exit 标 free,下次 enter 复用),~+150 LOC
- **R4** A28 hierarchical obs encoding 与 RL policy head 维度:policy head 输出维度 = base + 当前
  substate legal_actions max padding;全局 max(legal_actions across substate kind)。~+300 LOC
- **R5** Retrain wall time 估算 ~5h(host-native, container 1.5×)
- **R6** Phase 0 perf prototype 不达标:fallback path 检查 hook chain dispatch 优化 / proposal struct
  alloc 池化 / substate state recycle / provenance bound
- **R7** closure plain_key_fn 限制是否够表达:composite_key_fn(["cost", "id"]) builder,~+150 LOC

### 不在本 ADR 范围

由 v4 axiom 自然支持:始基反应 / on_battle_start / find_char / 数学 builtin / 跨方手牌 swap /
form-swap 替换 hooks / player decision 内嵌 propose hook

需 follow-up ADR(v4 不阻塞):detailed engine schema / helper lib API / substate body lint /
A24 meaningful-choice 检测算法

## v4 路径后续被取代

[`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/) 选择 v1 增量改造路线,**不上线
v4 prototype**。v4 prototype 30 axiom 设计工作"白做",但负面知识保留(哪些方向不必要);
[`../0018-dsl-v5-event-sourcing/`](../0018-dsl-v5-event-sourcing/) 也基于 v4 prototype 提出局部修补
(event-sourcing 替代 substate),同样未上线。

## References

- `docs/2_decisions/adr-0017-dsl_v4.md` (mirror)
- `gicg_engine/v2/` — prototype source(P1-T2/T6 评估是否删除)
- `gicg_engine/v2/v2_test.go` — 25 tests PASS (Stage 1-10)
- commit f788abc — typed schema + L3 obs
- commit 3a6d236 — A16 owner-detach tombstone
- memory `project_v1_is_production` — v2/ 旁路 prototype 从未上线
- [`../0018-dsl-v5-event-sourcing/`](../0018-dsl-v5-event-sourcing/) — 后续 event-sourcing 修补
- [`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/) — 后续 supersede 路线
