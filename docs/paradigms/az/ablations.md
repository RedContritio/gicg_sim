---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
parent: ./README.md
---

# AZ ablations

> 完整 Stage 3 sweep 数据见
> [`docs/5_history/algorithm_sweep_2026_04_28.md`](../../5_history/algorithm_sweep_2026_04_28.md)
> + [`docs/5_history/ablations/r001_r006_ablation.md`](../../5_history/ablations/r001_r006_ablation.md);
> r010 BC warm-start 数据点见
> [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)。
> 本 dossier 只列 paradigm-level lever 摘要。

## Stack comparison Stage 3 1-card stricter(三栈对照)

| 路线 | F1-D2 mean ± std | stricter PASS(≥ 0.40)? |
|---|---|---|
| PPO Stage 3 best(BC→PPO 1card fullobs)| 0.344 ± 0.062 | ❌ |
| AZ pure self-play(s064-066)| 0.104 ± 0.072 | ❌ |
| AZ + BC warm-start(r010 × 3 seed)| 0.167 ± 0.029 | ❌ |
| AZ multi-card baseline(s067 × 3 seed)| 0.062 ± 0.062 | ❌ |
| AZ D4 asymmetric mirror-break(s068 × 3 seed)| **0.271 ± 0.094** | ❌(但 seed43 0.375 first crossing PPO ceiling)|

## 主要 lever 摘要

| Lever | Effect on F1-D2 wr | Verdict |
|---|---|---|
| **BC warm-start(AZ 栈)** | **+0.063**(s064-66 → r010) | non-dominant — 与 PPO +0.24 反差大;AZ training destroys teacher signal |
| **multi-card breadth** | **−0.042**(s064-66 → s067) | paradigm-independent cliff(PPO 同 −0.24)|
| **D4 asymmetric mirror-break** | **+0.167**(s064-66 → s068) | partial reopen lever;mirror Nash 锁死部分主因 |
| **more rollouts(s069)** | **cancelled** | user 决策不继续(`project_rl_routes_closure_2026_05_12`)|

## 早期 architecture ablation(C1 era)

详 [`architecture.md`](./architecture.md) + [`docs/5_history/network_design_history.md`](../../5_history/network_design_history.md)。
关键 lever:

| Lever | Effect | Verdict |
|---|---|---|
| Network value as MCTS leaf | C1v1 大幅退步 | lambda=0 rollout 退路;混合 anneal 后才 viable |
| struct_readout + sid pinning(C1v7)| 反 ID 公平验证 PASS | paradigm-anchor breakthrough |
| char_skill_refs obs region | r005A → r006 +0.05 | retained |
| ExpandUnionK(K=3)| r003-r005A −0.05 | 移除(ADR 在 archive) |
| Fast lambda anneal(400 vs 1500)| r002 mcts_200 0.55 → 0.30 | retain default slow |

## 关键观察

1. **BC warm-start dominant 不传递跨 paradigm**:PPO +0.24 vs AZ +0.063,r010
   postmortem 假设 AZ value head 训练 / determinize / self-play 三者联合摧毁 BC prior。
2. **Multi-card 0.10 plateau paradigm-independent**:PPO 0.104 / AZ 0.062;
   combinatorial breadth 是 GICG 架构层 cliff,与 algorithm 关联弱。
3. **Mirror Nash 锁死是 plateau 主因之一**(s068 D4 +0.167)但**非唯一**:即使
   asymmetric,F1-D2 = 0.271 ± 0.094 仍未 stricter PASS。
4. **AZ Stage 0-2 与 PPO BC→PPO Stage 0-2 大致同强**:差异在 Stage 3 才暴露,
   paradigm-defining gap 是 stage-dependent。

## 决策路径

观察 1 + 2 + 3 触发 ADR-0010 partial reopen:closure 强命题(AZ 在 Stage 3
凡是 BC + curriculum stricter 必失败)被 s068 推翻一半。但 s069 cancelled +
user 评估含 NFSP / DMC 路线后选 DMC([`../dmc/`](../dmc/))→ AZ 实际 closure。
