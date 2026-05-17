# Design (retrospective)

## Consequences

### 为何 D1 belief network 不做(2026-04-28 PM 重新评估)

读 `training/az/determinize.py` 发现:
- ✅ Bayesian Dirichlet posterior 已实现于 `sample_opponent_dice`(α=1 prior + observed payment + tune evidence)
- ✅ Card pool 已知(SharedFixedPool / PerOpponentPool)
- ❌ Opponent policy belief 未建模 → 这是 NFSP 范畴

经典 belief network 在我们设定增量小。"opponent policy belief" = NFSP,合并到 D2。

### Decision tree(sweep 完成后)

| sweep 结果 | 决策 |
|---|---|
| s069/s070/s071 任一 vs F1-D2 ≥ 0.45 | compute/capacity 闭合 -0.27 gap → 推 production scale run |
| s069+s070+s071 都 ≈ 0.27,但 NFSP 或 deep CFR 突破 0.45 | 算法 deficit confirmed,但找到 fix → 推 NFSP/CFR scale |
| 全 sweep ≤ 0.30 | RL 真不可救 → re-confirm closure(ADR-0009 仍有效),最终 close |

## Tradeoffs revisited

### Verdict

Closure premature。s068 一个 +0.167 数据点已经推翻 "完全不可救" 的强命题。Sweep 跑完才能下 final
closure。

Production fallback 不变:r009 BC ckpt epoch_3 (vs F1-D2 = 0.75) 是确定性 production solution。
sweep 失败时回到 ADR-0009 closure。

## References

- `docs/2_decisions/adr-0010-rl_research_reopen.md` (mirror)
- [`../0009-rl-paradigm-pivot-terminus/`](../0009-rl-paradigm-pivot-terminus/) — 被部分推翻的 closure
- `docs/3_plans/algorithm_sweep_2026_04_28.md` — 详细 plan
- `docs/4_runs/registry.md` s068 — 数据
- memory `project_algorithm_sweep_2026_04_28` — 新 session 起点
