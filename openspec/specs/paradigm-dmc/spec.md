---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: paradigm-dmc
---

# Paradigm DMC — Deep Monte Carlo 算法层不变量

> DMC(Deep Monte Carlo)paradigm 的算法层 SHALL invariants。架构层继承
> [`../training-architecture/spec.md`](../training-architecture/spec.md),
> 本 spec 只列 DMC-specific 约束。

## 1. Purpose

DMC 是 GICG 当前 active-tier paradigm,Phase 3.5 review(2026-05)刚完成
41 项 critique 部分修订。主推路径,与 unified-training-pipeline change
是 first migration paradigm(P3-T8)。

## 2. Scope

**In scope**:
- DMC paradigm 实现的 6 protocol 接入要求
- MC episode return + λ-return optional
- Logit-as-Q loss(详 dmc_review §B.1)
- ε-greedy actor policy
- SHM replay buffer(N actor 共享)
- DMC tier = active

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture`
- DMC run 历史 / 41 项 critique → `docs/5_history/reviews/dmc_review.md` +
  `docs/paradigms/dmc/`
- F1-Dn baseline detail → `openspec/specs/eval-protocol/`

## 3. Core SHALL invariants

### D1. DMC 算法核心

1. **D1.1** DMC paradigm SHALL use Monte Carlo episode return for target
   (no bootstrapping by default;λ-return optional via cfg)。
2. **D1.2** DMC episode target Q(s, a) SHALL = sum of discounted future
   rewards from(s, a)to terminal;γ default 1.0(undiscounted)。
3. **D1.3** DMC SHALL NOT use TD bootstrapping at default mode;若启用
   λ-return,SHALL be paradigm cfg field 显式开启,不做 silent default。

### D2. Loss(logit-as-Q)

4. **D2.1** DMC loss SHALL use **logit-as-Q** formulation
   (详 `docs/5_history/reviews/dmc_review.md` §B.1):network policy logits
   are interpreted as Q-values directly,loss = MSE(logits[a], target_Q)。
5. **D2.2** Value head MAY be added for arena/eval,但 NOT used as TD target
   in default DMC training。
6. **D2.3** Loss reduction = mean over batch,no per-sample weighting。

### D3. Actor policy

7. **D3.1** DMC actor SHALL use ε-greedy policy:`act = argmax_a Q(s,a)`
   with probability `1 - ε`,uniform random valid action with probability
   `ε`。
8. **D3.2** Epsilon SHALL be paradigm cfg field,default 0.01;ε SHALL be
   constant during training(no annealing default)。
9. **D3.3** Eval policy SHALL be deterministic argmax(epsilon=0)。

### D4. Buffer

10. **D4.1** DMC buffer SHALL be `SHMRingBuffer`(N actor writer + 1 learner
    reader,详 `training-architecture` SHALL #9)。
11. **D4.2** Static dedup on `(obs_hash, action)` SHALL apply at sample time
    (recent-only,no time decay)。
12. **D4.3** Buffer capacity SHALL be cfg-driven,default 100_000。

### D5. Network heads

13. **D5.1** DMC network SHALL have a Q-as-logits head(`head_kinds={'q'}`)
    via generic `make_actor_critic(cfg, head_kinds={'q'},
    use_typed_damage=True)`(数学等价于历史 policy+value+delta 多 head 但
    只用 logits 当 Q,新装配后网络更轻量)。Value head MAY be added for
    arena/eval but is NOT default training head(per D2.2)。
14. **D5.2** Encoder = paradigm-agnostic typed obs encoder via generic
    `core/network/ActorCritic` backbone。`DmcAgent` SHALL 通过 DI 注入
    `hook_encoder=self.net.encoders['hook']`(详 `network-architecture/
    spec.md` invariants 12-13)。Imports SHALL use generic root:
    `from training.core.network import AgentBase, AgentConfig,
    ActorCritic, make_actor_critic`(SHALL NOT 引用
    `training.core.network.legacy.*`,已 git rm)。

### D6. Async pipeline

15. **D6.1** DMC SHALL run in async mode by default(`pipeline.mode = "async"`)
    with N actor(default 24,docker-limited)+ 1 learner + M eval worker。
16. **D6.2** Stale weights tolerance:lag p99 ≤ 500 step(详
    `training-architecture` SHALL #9)。

### D7. Tier

17. **D7.1** DMC tier SHALL be `active`(主推 paradigm)。
18. **D7.2** F1-D2 win rate target ≥ 0.30(条件触发 G3 Go 化 follow-up
    change)。

## 4. Cross-references

- 主 training architecture →
  [`../training-architecture/spec.md`](../training-architecture/spec.md)
- DMC review 41 critique → `docs/5_history/reviews/dmc_review.md`
- DMC paradigm dossier → `docs/paradigms/dmc/`
- G3 DMC actor Go follow-up → 待启动独立 change(F1-D2 ≥0.30 触发)
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)

## 5. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)—
  MODIFY D5.1/D5.2(generic ActorCritic via `make_actor_critic` with
  `head_kinds={'q'}` 单 Q head + AgentBase DI 注入 hook_encoder);imports
  切到 `core/network` root,SHALL NOT 引用 `core/network/legacy/*`(已
  git rm)。
- **Version**:0
- **Implementation**:Phase 3-T8 落地(first migration);unified-training-pipeline
  主 migration target;`core-network-generic-promotion` Phase 2B
  (2026-05-17)DMC 接 generic backbone(单 Q head)完成
- **Tier**:active — 主推,接受 new run + ablation
