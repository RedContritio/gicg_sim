---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: paradigm-az
---

# Paradigm AZ — AlphaZero 算法层不变量

> AZ(AlphaZero)paradigm 的算法层 SHALL invariants。架构层(Paradigm
> protocol / EpisodeRunner / NetworkProvider)继承
> [`../training-architecture/spec.md`](../training-architecture/spec.md),
> 本 spec 只列 AZ-specific 约束。

## 1. Purpose

AZ 是 GICG 在 RL closure 后保留的 maintenance-tier paradigm,2026-04 C1v7
+ r010 系列在产。本 spec 治理 AZ 算法层不变量:
- MCTS-driven selfplay episode
- KL policy loss + MSE value loss
- Replay buffer + static dedup
- (Policy, value)双 head 网络

## 2. Scope

**In scope**:
- AZ paradigm 实现的 6 protocol(Paradigm / Collector / Buffer / LossComputer /
  EpisodePolicy / NetworkProvider 各自 AZ-specific 实现要求)
- IS-MCTS + leaf eval via NetworkProvider 协议
- KL + MSE loss 数学契约
- Replay buffer + static dedup 配置范围

**Out of scope**:
- MCTS 树结构 / PUCT 公式细节 — `gicg_mcts/` Go 库 spec(待 `search-ismcts`
  capability spec)
- Obs / action 张量编码 — `openspec/specs/rl-obs/`(待落地)
- 通用 EpisodeRunner / NetworkProvider — `training-architecture` spec
- AZ run 历史 / closure 决策 — `docs/paradigms/az/` dossier

## 3. Core SHALL invariants

### A1. AZ 算法核心

1. **A1.1** AZ paradigm SHALL use IS-MCTS(Information-Set MCTS,from
   `gicg_mcts/`)for selfplay episode generation。
2. **A1.2** AZ MCTSPolicy.act() SHALL call `provider.forward()` at every
   tree leaf expansion(no random rollout)。
3. **A1.3** AZ training target SHALL be(π, z):π = MCTS visit count
   distribution,z = episode reward(no bootstrapping)。

### A2. Loss

4. **A2.1** AZ loss SHALL = `KL(π_mcts, π_net) + MSE(z_episode, v_net)`,
   per-sample;reduction = mean over batch。
5. **A2.2** Loss weighting fixed:`policy_weight = 1.0, value_weight = 1.0`
   (任何 weighting override SHALL 走 paradigm cfg field)。
6. **A2.3** No entropy bonus(unlike PPO);MCTS exploration via Dirichlet
   noise at root(`mcts_noise_alpha` cfg)。

### A3. Buffer

7. **A3.1** AZ buffer SHALL be `ReplayBuffer`(from `training/core/buffer/replay.py`)
   with static dedup on `(obs_hash, mcts_visit_hash)`。
8. **A3.2** Buffer capacity SHALL be cfg-driven,default 200_000 transitions。
9. **A3.3** Sample SHALL be uniform random over buffer + dedup mask。

### A4. Network heads

10. **A4.1** AZ network SHALL have 2 heads:`policy_head(logits)` +
    `value_head(scalar)`,both fed by shared encoder。canonical head
    classes 由 `training/paradigms/az/network.py::BASIC_HEAD_CLASSES`
    枚举(`PolicyHead` + `ValueHead`,均 from
    `training/core/network/heads.py`)。
11. **A4.2** Encoder SHALL 基于 C1v7 struct_readout(`training/core/network/struct_readout.py`)。
    Generic `ActorCritic`(`training/core/network/actor_critic.py`)由
    `Agent` 通过 `make_actor_critic(cfg, head_kinds={'policy', 'value',
    'delta'}, use_typed_damage=True)` 装配,`AgentBase` 通过 DI 注入
    `hook_encoder=self.net.encoders['hook']`(详 `network-architecture/
    spec.md` invariants 12-13)。

### A5. Collector

12. **A5.1** AZ Collector SHALL be `SelfPlayCollector`,each episode is a
    full self-play game with MCTS at both sides。
13. **A5.2** Both sides SHARE the same network(true selfplay,unless
    arena / eval scenario specifies historical opp)。
14. **A5.3** `requires_network_in_collect = True`(MCTS leaf eval needs
    network forward)。
15. **A5.4** AZ paradigm 内任何持有 `card_pool_spec` 字段的 site SHALL
    construct via `make_pool_spec(scenario, resolve_pool_refs(scenario))`
    (`training/paradigms/az/pool_spec.py`)。SHALL NOT 把
    `resolve_pool_refs()` 的 dict return 直接 assign 给 `card_pool_spec`
    或传给 `sample_hidden_state` / `mcts_search` 等下游 — 后者 expects
    `determinize.CardPoolSpec` protocol(`.sample_opponent_deck(rng, pub)`
    method),dict 不 conform → 运行时 AttributeError。3 个 caller site
    SHALL share 同一 construction discipline:`AZSelfPlayCollector.__init__`
    (`collector.py`)、`_az_build_policy`(`collector.py`,async actor 工厂)、
    `AZParadigm.make_episode_policy`(`paradigm.py`),与 `inference_worker.py`
    已 proven pattern 一致。`make_pool_spec()` 内 `disjoint_teams=True` →
    `PerOpponentPool`,else → `SharedFixedPool`;paradigm 内 caller SHALL NOT
    直接 import 这两个 class — `make_pool_spec` 是 single entry point。

### A6. Tier

15. **A6.1** AZ tier SHALL be `maintenance`(per memory project_rl_routes_closure_2026_05_12)。
    AZ SHALL NOT receive new production run after 2026-05-12,but reproducibility
    SHALL be preserved。
16. **A6.2** **r009 ckpt production fallback 撤销(SUPERSEDED)** —
    > ~~r009 ckpt as production fallback per ADR-0009~~ — SUPERSEDED by
    > `core-network-generic-promotion` (archive 2026-05-17)。理由:r009
    > ckpt 自 2026-05-08 ADR-0019 typed obs ckpt break 后 strict-load 名
    > 存实亡,non-strict load 也仅 best-effort。User 决策正式撤销:接受
    > 全部 ckpt 失效,需要 production fallback 时重 train r009-equivalent
    > on new schema。ADR-0009 同步 SUPERSEDED-BY:
    > `core-network-generic-promotion`。

## 4. Implementation refs

az-paradigm-rewrite Phase 5(2026-05-16)git rm `paradigms/az/legacy/`,
`core-network-generic-promotion` Phase 1/2(archive 2026-05-17)git rm
`core/network/legacy/` + generic primitives 提升 后,AZ adapter 自包含 +
共用 generic backbone,全部模块在 `training/paradigms/az/` 顶层:

- `paradigm.py` — `AZParadigm`(实现 `core.protocols.Paradigm`)
- `collector.py` — `SelfPlayCollector`(A5)
- `policy.py` — MCTS-driven `EpisodePolicy`(A1.1-A1.2)
- `loss.py` — KL + MSE loss(A2)— AZ paradigm-local,SHALL NOT 依赖历史
  `core/network/legacy/loss.py::az_losses`(已 git rm)
- `network.py` — `Agent`(via `make_actor_critic` + DI hook_encoder)+
  `AgentConfig` + `BASIC_HEAD_CLASSES`(A4)
- `buffer.py` — `ReplayBuffer` 含 static dedup(A3)
- `selfplay.py` — `play_self_game`(A1.3)
- `mcts/` — IS-MCTS Python 实现包(A1.1)
- `mcts_go.py` + `mcts_go_bindings.py` — Go MCTS L3 cgo bridge
- `determinize.py` — IS-MCTS information-set determinization
- `arena.py` — AZ-internal arena evaluation
- `inference_pool.py` + `inference_worker.py` — 并行 inference 池
- `train_step.py` + `train_az.py` + `train_loop/` — 训练循环
- `config.py` + `config_loader.py` — AZ-specific cfg + loader
- `pool_spec.py` — pool spec helper

Imports SHALL use generic root: `from training.core.network import
ActorCritic, AgentBase, AgentConfig, make_actor_critic`(SHALL NOT 引用
`training.core.network.legacy.*`,已退役)。

## 5. Cross-references

- 主 training architecture → [`../training-architecture/spec.md`](../training-architecture/spec.md)
- IS-MCTS engine spec → [`../search-ismcts/spec.md`](../search-ismcts/spec.md)
- AZ paradigm dossier → `docs/paradigms/az/`
- AZ closure history → memory `project_rl_closure_2026_04_28` + `project_rl_routes_closure_2026_05_12`
- AZ network detail → `docs/paradigms/az/architecture/c1v7.md`(待 ship)
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)
- AZ legacy retire change(active,Phase 6 后 archive)→
  [`../../changes/az-paradigm-rewrite/`](../../changes/az-paradigm-rewrite/)

## 6. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)—
  MODIFY A4.2(generic ActorCritic via `make_actor_critic` + AgentBase
  DI 注入 hook_encoder);+A6.2 r009 ckpt production fallback SUPERSEDED
  (ADR-0009 同步)。Imports 切到 `core/network` root,SHALL NOT 引用
  `core/network/legacy/*`(已 git rm)。
- **Revised**:2026-05-17(`az-pool-spec-type-fix` archive)— +A5.4
  pool spec single-point construction discipline(治理 3 处 caller copy/paste
  同 dict→spec anti-pattern,unblock smoke_full A1.6 contract)。
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied;Phase 5
  (2026-05-16)git rm `paradigms/az/legacy/` 完成 paradigm 自包含 retire;
  `core-network-generic-promotion` Phase 1/2(2026-05-17)git rm
  `core/network/legacy/` + generic primitives 提升
- **Tier**:maintenance — 不接受 new production run,保留 reproducibility
