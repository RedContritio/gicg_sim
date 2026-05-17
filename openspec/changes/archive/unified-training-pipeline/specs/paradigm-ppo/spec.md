---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: paradigm-ppo
change_id: unified-training-pipeline
---

# Spec delta — paradigm-ppo(new capability)

> 新 capability spec。PPO(Proximal Policy Optimization)算法层 SHALL
> invariants。架构层继承 `training-architecture`,本 spec 只列 PPO-specific
> 约束。

## 1. Purpose

PPO 是 GICG 2026-04 早期 RL 主路径,Stage 3 30+ ablation(s021-s054)+
F1-D2 ≥ 0.40 物理不可达诊断后,由 `archive/0008-rl-paradigm-pivot` closed
转 `frozen` tier。本 spec 治理 PPO 算法层不变量,保证可复盘 + lever 验证:

- On-policy GAE rollout
- Clipped surrogate + value MSE + entropy bonus 三项 loss
- (Policy, value)双 head 网络
- Rollout buffer(每 iter clear)

D2 决策(本 change 内):PPO **迁移**而非 archive,通过新管线 reproducible
(memory `project_stage3_full_diagnosis` 信息密度高,值得长期可访问)。

## 2. Scope

**In scope**:
- PPO paradigm 实现的 6 protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider PPO-specific 实现要求)
- GAE return / advantage 估计
- Clipped surrogate loss 数学契约
- Rollout buffer 每 iter clear
- 复盘范围(s021-s054 ablation reproducibility)

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture`
- PPO run 历史 / Stage 3 closure → `docs/paradigms/ppo/` +
  `docs/5_history/ablations/stage3_ppo_closure.md`
- Opponent pool / ELO(memory `project_pool_elo_design` OBSOLETE)→ AZ D4
  废除,本 spec 不重申

## 3. Core SHALL invariants

### P1. PPO 算法核心

1. **P1.1** PPO paradigm SHALL use on-policy rollout(no replay)+ GAE
   advantage estimation,λ default 0.95。
2. **P1.2** Rollout horizon SHALL be cfg-driven `pipeline.rollout.n_steps`,
   default 2048;vec env optional(`vec_env_size` cfg,default 1)。
3. **P1.3** Discount γ default 0.99(PPO 时代沿用,与 AZ/DMC γ=1.0 不同
   是 paradigm decision,不变)。

### P2. Loss(三项 sum)

4. **P2.1** PPO loss SHALL = `clipped_surrogate + value_coef * value_mse -
   entropy_coef * entropy_bonus`,3 项 sum;clipping ε default 0.2。
5. **P2.2** Value loss MAY use clipped value form(详 Schulman 原文)。
6. **P2.3** Entropy bonus SHALL be paradigm cfg,default `entropy_coef =
   0.01`;value coef default 0.5。

### P3. Actor policy

7. **P3.1** PPO actor SHALL sample from policy logits(`Categorical(logits).sample()`)
   during rollout;NOT argmax。
8. **P3.2** Eval policy SHALL be deterministic argmax(rollout sampling for
   exploration only)。
9. **P3.3** Old-policy log_prob SHALL be stored in rollout buffer for
   importance ratio computation(loss 计算 prerequisite)。

### P4. Buffer

10. **P4.1** PPO buffer SHALL be `RolloutBuffer`(from
    `training/core/buffer/rollout.py`),**SHALL be cleared after each
    optimization iteration**(on-policy invariant)。
11. **P4.2** Buffer capacity = rollout_horizon × vec_env_size(no replay,
    no static dedup)。
12. **P4.3** Sample SHALL be sequential minibatch shuffle within rollout
    (no cross-iteration sampling)。

### P5. Network heads

13. **P5.1** PPO network SHALL have 2 heads:`policy_head(logits)` +
    `value_head(scalar)`,both fed by shared encoder。
14. **P5.2** Heads MAY be separated(no shared trunk)by paradigm cfg
    `network.heads_share_trunk = false`;default `true`(GICG 沿用 AZ-style
    shared encoder)。

### P6. Tier

15. **P6.1** PPO tier SHALL be `frozen`(per archived `0008-rl-paradigm-pivot`)。
16. **P6.2** PPO migration to unified pipeline SHALL preserve s021-s054
    ablation reproducibility(同 cfg + 同 seed → 同 F1-D2 ±0.02 noise band)。
17. **P6.3** New PPO production run SHALL NOT be launched without OpenSpec
    change unfreezing tier(避免重复 PPO 时代 closure 上的资源浪费)。

## 4. Cross-references

- 主 training architecture →
  [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md)
- PPO paradigm dossier → `docs/paradigms/ppo/`
- Stage 3 closure → `archive/0008-rl-paradigm-pivot` + memory
  `project_stage3_full_diagnosis`
- Pool/ELO history(OBSOLETE)→ memory `project_pool_elo_design` +
  `project_pool_elo_followups`
- Phase 4 实施 →
  [`../../tasks/phase4-other-paradigms.md`](../../tasks/phase4-other-paradigms.md) §3

## 5. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied
- **Tier**:frozen — 仅保留 reproducibility,不接受 new run
