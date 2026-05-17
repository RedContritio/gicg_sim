---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
parent: ./README.md
---

# AZ postmortems

> Postmortem canonical 来源在 [`docs/5_history/`](../../5_history/),本 dossier
> 只列入口 + paradigm-level 失败 root cause 总结。

## 主要 postmortem 来源

| Topic | Canonical doc |
|---|---|
| C1 family 早期失败诊断 | [`docs/5_history/postmortems/c1_postmortem.md`](../../5_history/postmortems/c1_postmortem.md) |
| C1v6 修复 plan(6 hook gradient bug)| [`docs/5_history/postmortems/c1v6_plan.md`](../../5_history/postmortems/c1v6_plan.md) |
| C1v0-v7 完整网络架构演化 | [`docs/5_history/network_design_history.md`](../../5_history/network_design_history.md) |
| r010 BC warm-start destruction | [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md) |
| s067-s069 algorithm sweep | [`docs/5_history/algorithm_sweep_2026_04_28.md`](../../5_history/algorithm_sweep_2026_04_28.md) |
| MCTS engine history | [`docs/5_history/search_history.md`](../../5_history/search_history.md) |
| Determinize audit | [`docs/5_history/audits/determinize_audit.md`](../../5_history/audits/determinize_audit.md) |
| Env audit | [`docs/5_history/audits/env_audit.md`](../../5_history/audits/env_audit.md) |
| Generalization review | [`docs/5_history/audits/generalization_review.md`](../../5_history/audits/generalization_review.md) |

## Paradigm-level 失败 root cause(总结)

### 1. Net-as-leaf(C1v1)

AlphaZero 标准设计 — net value 直接做 MCTS leaf。在 GICG 上 net 训得不准时
**反而拉低** search 质量(vs mcts_200 ≤ 0.05)。Fix:lambda=0 rollout 训练
(C1v2)+ lambda anneal restore(C1v3+)。Memory: `project_c1_failure_diagnosis`。

### 2. Hook gradient bug(C1v5-v6,6 项修复)

DSL hook chain 上 autograd 跨 skill 污染。`F` 节点(commit hash 见 c1v6_plan)
前所有 ckpt 作废。Fix:6 项独立修复 + regression test。

### 3. CrossAttention 满熵(C1v6+ 仍存在)

Pool 零空间 C18 定理 — cross-attn 在 GICG action pool 上 mathematically 满熵。
未做 attn supervision 修复;C1v7 用 **struct_readout 直接绕过**(reading from
slot-perm structured features,不依赖 attn output)。Memory: `project_cross_attn_saturation`。

### 4. BC warm-start destruction(r010)

PPO 路线 BC warm-start +0.24 dominant,AZ 路线只 +0.063。假设根因:

- **Value head 训练**:AZ 训 value(MCTS-target value MSE),BC ckpt 不带 value,
  random-init value head 早期 noise + gradient 通过 shared trunk 流回 policy。
- **Determinize**:opp turn 用 sampled belief,policy 看到的 distribution 与 BC
  data(F1-D2 teacher full-info)不一致,distribution shift fast。
- **Self-play collapse**:无 BC anchor 的同时 self-play 标 reward 噪声大。

完整诊断 → [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)。

### 5. Stage 3 plateau(多层成因)

- **Card combinatorial breadth**(paradigm-independent):1-card 0.104 → 3-card 0.062
- **Mirror Nash 锁死**(主因之一,partial 推翻 by s068):mirror match 下双方
  symmetric Nash converge to non-discriminating policy
- **F1-D2 teacher 自身 ceiling**:BC hard-match 0.354(tied_mask mean 2.83);
  AZ 不依赖 BC 但 evaluator(F1-D2 ladder)本身 noisy

完整 sweep 数据 → [`docs/5_history/algorithm_sweep_2026_04_28.md`](../../5_history/algorithm_sweep_2026_04_28.md)。

## Closure 决策路径

- **2026-04-18**:C1v7 反 ID 公平验证 PASS argmax vs mcts_200 = 0.45 — paradigm
  acceptance milestone。
- **2026-04-26**:Stage 0-2 PASS;Stage 3 1-card baseline F1-D2 = 0.104 ± 0.072 显弱。
- **2026-04-28(AM)**:closure 强命题(AZ Stage 3 不 viable)— memory
  `project_rl_closure_2026_04_28`。
- **2026-04-28(PM)**:s068 D4 asymmetric F1-D2 = 0.271 ± 0.094(+0.167)推翻强命题
  → ADR-0010 partial reopen。
- **2026-04-28(后续)**:s069 more_rollouts probe pending → user-killed at seed42 →
  优先 ADR-0011 改造(pool versioning)。
- **2026-05-12**:user 评估扩展 closure 集合包含 NFSP / Deep CFR redo / AZ-on-v_phase2,
  确认 DMC([`../dmc/`](../dmc/))作新主线 — memory `project_rl_routes_closure_2026_05_12`。
- **2026-05-12**:s070 v_phase2 凯亚 mirror probe undertrained → AZ 实际让位 DMC。

## 不再 actionable 的 follow-up(知识保留)

- **AZ + BC warm-start with frozen value head 0.5 epoch**:r010 postmortem 提出但
  未试,可能 partially recover BC signal
- **AZ + asymmetric + more_rollouts(s069)**:cancelled;若 DMC 路线 closure 可重启
- **Loss-adaptive lambda**(memory `project_r002_fast_anneal_worse`):online loss
  signal 触发 anneal acceleration,未实现
- **Pool 零空间 attn supervision**:C1v7 struct_readout 绕过即可,若 C2 失败再考虑
