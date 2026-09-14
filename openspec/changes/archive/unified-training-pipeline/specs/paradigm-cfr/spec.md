---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: paradigm-cfr
change_id: unified-training-pipeline
---

# Spec delta — paradigm-cfr(new capability)

> 新 capability spec。CFR(Deep Counterfactual Regret Minimization)算法
> 层 SHALL invariants。架构层(Paradigm protocol / EpisodeRunner /
> NetworkProvider)继承 `openspec/specs/training-architecture/spec.md`,本
> spec 只列 CFR-specific 约束。

## 1. Purpose

CFR 是 GICG r008 prototype 时代主路径,2026-04-23 之后因 r008 postmortem
(iter 199 < random + 策略震荡)+ AZ 闭环胜出转入 `frozen-research` tier。
本 spec 治理 CFR 算法层不变量,保证 reproducibility 与可对照:

- OS-MCCFR(Outcome-Sampling Monte Carlo CFR)traversal
- Reservoir buffer(advantage + strategy)
- Advantage MSE + Strategy MSE 双 loss
- (Avg_policy, advantage)双 head 网络

## 2. Scope

**In scope**:
- CFR paradigm 实现的 6 protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider 各自 CFR-specific 实现要求)
- OS-MCCFR traversal 算法契约(player iteration / cf-reach)
- Reservoir sampling 半生命期约定
- Advantage / Strategy 双 reservoir 隔离

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture` spec
- CFR run 历史 / r008 postmortem → `docs/paradigms/cfr/` dossier +
  memory `project_r008_postmortem`
- Obs / action 张量编码 → `openspec/specs/rl-obs/`(待落地)

## 3. Core SHALL invariants

### C1. CFR 算法核心

1. **C1.1** CFR paradigm SHALL use OS-MCCFR(Outcome-Sampling MCCFR)for
   traversal,SHALL NOT 用 vanilla CFR(全树遍历不可行)。
2. **C1.2** Traversal SHALL alternate by `traverser_player` ∈ {0, 1};单
   iteration 内一个 player 为 traverser,另一为 opponent(sampling)。
3. **C1.3** Counterfactual reach probability SHALL be tracked along
   traversal path;regret update SHALL be cf-reach-weighted。

### C2. Loss(双 head)

4. **C2.1** CFR loss SHALL = `advantage_mse + strategy_mse`,两 head 独立
   target,SHARED encoder。
5. **C2.2** Advantage target SHALL = clipped regret(positive part 或
   regret-matching+);strategy target SHALL = normalized cumulative strategy。
6. **C2.3** Loss reduction = mean over batch,no policy-strategy weighting
   override(避免 r008 时观察的 loss-quality 脱钩问题,见 memory)。

### C3. Buffer(reservoir 双隔离)

7. **C3.1** CFR SHALL use **two separate reservoirs**:`advantage_reservoir`
   + `strategy_reservoir`,SHALL NOT 合并(advantage 短期、strategy 长期)。
8. **C3.2** Reservoir SHALL be `ReservoirBuffer`(from
   `training/core/buffer/reservoir.py`),uniform sampling with reservoir
   size cap。
9. **C3.3** Reservoir capacity SHALL be cfg-driven,default advantage =
   200_000,strategy = 1_000_000(history-long retention)。

### C4. Network heads

10. **C4.1** CFR network SHALL have 2 heads:`avg_policy_head(logits)` +
    `advantage_head(per-action scalar)`,both fed by shared encoder。
11. **C4.2** Eval / production inference SHALL use `avg_policy_head` only;
    `advantage_head` is training-only。

### C5. Collector

12. **C5.1** CFR Collector SHALL be `TraversalCollector`,parallel by
    Python thread(I/O-bound,Go engine 持锁释放后并行)。
13. **C5.2** `requires_network_in_collect = True`(advantage 估计需 forward)。
14. **C5.3** Both players SHARE the network during traversal(symmetric
    selfplay assumption)。

### C6. Tier

15. **C6.1** CFR tier SHALL be `frozen-research`(per memory
    `project_rl_routes_closure_2026_05_12`)。
16. **C6.2** CFR SHALL preserve r008 reproducibility — 本 change 迁移
    后,同 cfg + 同 seed SHALL 复现 r008 ckpt iter 20 / 100 / 199 win rate
    (±5% noise band)。
17. **C6.3** New CFR production run SHALL NOT be launched without OpenSpec
    change unfreezing tier(避免重复 r008 资源浪费)。

## 4. Cross-references

- 主 training architecture →
  [`../../../../../specs/training-architecture/spec.md`](../../../../../specs/training-architecture/spec.md)
- CFR paradigm dossier → `docs/paradigms/cfr/`
- r008 postmortem → memory `project_r008_postmortem`
- CFR closure history → memory `project_rl_routes_closure_2026_05_12`
- Phase 4 实施 →
  [`../../tasks/phase4-other-paradigms.md`](../../tasks/phase4-other-paradigms.md) §4

## 5. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied
- **Tier**:frozen-research — 仅保留 reproducibility,不接受 new run
