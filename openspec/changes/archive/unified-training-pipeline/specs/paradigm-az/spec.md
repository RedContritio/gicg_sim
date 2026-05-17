---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: paradigm-az
change_id: unified-training-pipeline
---

# Spec delta — paradigm-az(new capability)

> 新 capability spec。AZ(AlphaZero)算法层 SHALL invariants。架构层
> (Paradigm protocol / EpisodeRunner / NetworkProvider)继承
> `openspec/specs/training-architecture/spec.md`,本 spec 只列 AZ-specific
> 约束。

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
    `value_head(scalar)`,both fed by shared encoder。
11. **A4.2** Encoder MAY be C1v7 struct_readout based(default)or vanilla
    transformer(legacy);cfg `network.encoder_kind` 切换。

### A5. Collector

12. **A5.1** AZ Collector SHALL be `SelfPlayCollector`,each episode is a
    full self-play game with MCTS at both sides。
13. **A5.2** Both sides SHARE the same network(true selfplay,unless
    arena / eval scenario specifies historical opp)。
14. **A5.3** `requires_network_in_collect = True`(MCTS leaf eval needs
    network forward)。

### A6. Tier

15. **A6.1** AZ tier SHALL be `maintenance`(per memory project_rl_routes_closure_2026_05_12)。
    AZ SHALL NOT receive new production run after 2026-05-12,but reproducibility
    SHALL be preserved。

## 4. Cross-references

- 主 training architecture → [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md)
- IS-MCTS engine spec → [`../../../../specs/search-ismcts/spec.md`](../../../../specs/search-ismcts/spec.md)
- AZ paradigm dossier → `docs/paradigms/az/`
- AZ closure history → memory `project_rl_closure_2026_04_28` + `project_rl_routes_closure_2026_05_12`
- AZ network detail → `docs/paradigms/az/architecture/c1v7.md`(待 ship)
- Phase 4 实施 → [`../../tasks/phase4-other-paradigms.md`](../../tasks/phase4-other-paradigms.md) §2

## 5. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied
- **Tier**:maintenance — 不接受 new production run,保留 reproducibility
