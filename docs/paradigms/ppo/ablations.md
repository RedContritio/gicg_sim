---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# PPO ablations

> 完整 29-ablation diagnosis 见
> [`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)
> (canonical source,本 dossier 不复制)。本文给 paradigm-level lever 摘要。

## Lever summary(Stage 3 4-factor matrix)

| Lever | Effect on F1-D2 wr | Verdict |
|---|---|---|
| **BC warm-start** | **+0.24(dominant)** | s054 scratch peak ~0.11 vs s033 BC peak ~0.41;唯一 paradigm-defining lever |
| **partial obs(mask enemy_dice)** | +0.13(1-card 下) | s028-30 vs s033/39/40;Stage 2 BC pretrain soft_match 73→66%量化 enemy dice info value |
| **F1-D3 teacher(vs F1-D2)** | +0.10 marginal | s036/s044/s045 vs s028-30;more thoughtful teacher 小幅提高,combo 非加性 |
| **PPO oscillation** | ±0.10-0.15 | s053 long-1000-iter F1-D2 区间 [0.18, 0.42],noise floor 高 |
| **Combo(BC + obs + teacher)** | **0.281**(predicted 0.45) | s050-s052;NOT additive — paradigm ceiling 物理硬约束 |

## 早期 ablation(r001-r006)

obs / anneal lever ablation(C1v7 era,pre-pivot):

| Lever | Run | g400 mcts_200 |
|---|---|---|
| baseline | r001 | 0.55 |
| fast lambda_anneal | r002 | 0.30(-0.25,fast 显劣) |
| char_skill_refs obs + K=3 | r003 | 0.25 |
| slow + K=3 | r004 | 0.40(slow 是 fast harm 主因) |
| slow + K=1 | r005A | 0.45 |
| slow + K=1 − char_skill_refs | r006 | 0.40(char_skill_refs +0.05 净正) |

完整分析 → [`docs/5_history/ablations/r001_r006_ablation.md`](../../5_history/ablations/r001_r006_ablation.md)。

## 关键观察

1. **BC warm-start = dominant lever**:其他 3 factor 单独 marginal,合并非加性。
2. **F1-D2 ≥ 0.40 物理不可达 in BC→PPO**:30+ ablation 全程未跨过(peak single-seed 0.406,multi-seed mean ≤ 0.344)。
3. **PPO oscillation 限制 multi-seed std**:long-train ±0.15 区间,n=3 std ≥ 0.06。
4. **Multi-card pool 显著困难**:1-card → 3-card,F1-D2 0.344 → 0.104(-0.24,与
   BC lever 同量级)。Combinatorial breadth 是另一层 paradigm-level cliff。

## 决策路径

观察 2 + 4 触发 ADR-0009 curriculum closure:Stage 3 ceiling 既低 又对 card pool
breadth 极敏感 → curriculum 4/5(更大 pool)路径无意义,paradigm 改 AZ search。
完整决策推理 → [`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`](../../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/)。
