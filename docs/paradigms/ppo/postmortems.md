---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
parent: ./README.md
---

# PPO postmortems

> 失败分析的 canonical 来源在 [`docs/5_history/`](../../5_history/),本 dossier
> 只列入口 + paradigm-level 复盘观察。

## 主要 postmortem 来源

| Topic | Canonical doc |
|---|---|
| Stage 3 BC→PPO 4-factor closure | [`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md) |
| r001-r006 obs/anneal ablation | [`docs/5_history/ablations/r001_r006_ablation.md`](../../5_history/ablations/r001_r006_ablation.md) |
| PPO pre-AZ era 整体归档 | [`docs/5_history/eras/ppo_pre_az/`](../../5_history/eras/ppo_pre_az/) |
| Curriculum plan termination | [`docs/5_history/curriculum/plan.md`](../../5_history/curriculum/plan.md) |

## Paradigm-level 失败 root cause(总结)

1. **Self-play collapse(s011-s012)**:Stage 1 mirror + stochastic env 下
   双方都 Tune,draw dynamics 不教 attack。Fix opponent 解,但暴露
   **opponent overfit**(s013 学到 F1-D1 56%,F1-D2 generalize 0%)。

2. **Value gradient 淹没 policy gradient(s010-s011)**:reward=±80 + terminal=±60
   配 value_coef=0.5 + shared trunk → ratio ~7500:1,policy gradient signal 微弱。
   降 terminal=10 + value_coef=0.1 修复 value side,但 self-play collapse 是另一层。

3. **Tied teacher noise ceiling(s015 hard_match 0.354)**:F1-D2 teacher
   random tiebreak over mean 2.83 ties per decision → BC hard-match physical
   ceiling 0.354。soft target 突破之(s016d 73%),但 distillation noise floor 仍在。

4. **Stage 3 multi-card 0.10 plateau**:1-card → 3-card pool,F1-D2 0.344 → 0.104。
   card combinatorial breadth 超出 BC distillation + PPO fine-tune capacity。

## Closure 决策路径

- **2026-04-24**:r007 1500g killed(I5 deadlock,arena collapse trajectory)。
- **2026-04-24**:r008 Deep CFR detour 启动(详 [`../cfr/`](../cfr/))。
- **2026-04-25**:pure PPO Stage 1 5 pipeline 全 FAIL(s009-s014)→ ADR-0008 paradigm pivot:
  接受 BC warm-start 是 pure-RL paradigm 在 GICG action distribution 长尾下的
  必要 anchor。
- **2026-04-25**:s017 BC→PPO Stage 1 PASS F1-D2=0.500 → 4 factor ablation 开启。
- **2026-04-26**:Stage 3 best cell 0.344 ± 0.062 + scratch peak 0.11 + combo
  non-additive → ADR-0009 closure。
- **2026-04-26**:pivot AZ([`../az/`](../az/));BC ckpt 作 production fallback
  ([`../bc/`](../bc/))。

完整决策上下文 → [`openspec/changes/archive/0008-rl-paradigm-pivot/`](../../../openspec/changes/archive/0008-rl-paradigm-pivot/)
+ [`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`](../../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/)。

## 不再 actionable 的 follow-up(知识保留)

PPO closure 后未继续追的方向(若未来重启 PPO 路线可参考):

- **Loss-adaptive lambda**(memory `project_r002_fast_anneal_worse`):lambda anneal
  schedule by online loss signal 而非 fixed games。
- **F1-D2 dice_greedy=true teacher**(memory `feedback_quantify_with_game_rules`):
  对手强度提升,可能改 tied_mask 分布;未试过 BC pretrain。
- **Pure offline imitation + on-policy distillation**(无 PPO):BC 73% soft_match
  本身 vs F1-D2 = 0.75(详 [`../bc/`](../bc/)),offline-only 路径可能在
  Stage 4/5 仍 actionable,但与 PPO paradigm 边界外。
