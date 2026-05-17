# ADR-0010: RL research reopened — closure 部分推翻,跑 algorithm sweep 至 final verdict

> **MOVED to `openspec/changes/archive/0010-rl-research-reopen/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0010-rl-research-reopen/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0010-rl-research-reopen/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**Date:** 2026-04-28 PM(同日下午)
**Status:** Accepted
**Relates to:** [`adr-0009-rl_paradigm_pivot_terminus.md`](adr-0009-rl_paradigm_pivot_terminus.md)(closure,被本 ADR 部分推翻)
**Decided by:** s068 D4 mirror-break probe(2σ 显著 +0.167)+ 用户希望"完成全部"

## Context

ADR-0009 上午基于 PPO/AZ/AZ+BC 三栈 × 5 stage = 15 数据点全失败,closure self-play RL。
下午 s068 D4 mirror-break probe(asymmetric teams 赤蝶 vs 墨客,Stage 3 1-card)给:

- F1-D2 mean = **0.271 ± 0.078** (n=3)
- vs s064-066 mirror baseline 0.104:**+0.167 显著超 noise (>2σ)**

意味着 mirror Nash 锁死**部分**贡献了 RL plateau。closure "RL 在本游戏类不可救" 命题**被部分推翻**。

## Decision

1. **Reopen RL research**:跑完所有候选 algorithm fix,直到全部失败才 final closure
2. **保留 ADR-0009 作为 closure 的初始判断**(基于当时数据合理),本 ADR 作为后续 update
3. **Production fallback 不变**:r009 BC ckpt epoch_3 (vs F1-D2 = 0.75) — 若 sweep 全 fail,closure 仍生效

## Algorithm sweep plan

| ID | 假设 | 配置 | 工作量 | 优先级 |
|---|---|---|---|---|
| **s069 (running 14:21)** | compute deficit | s068 spec + n_rollouts 100→500 | 5h | P0 |
| s070(待) | training duration 不够 | s068 spec + n_games 200→1000 | 5h | P1, conditional |
| s071(待) | capacity 不够 | s068 spec + d_model 128→256 | 2h | P1 |
| **D2 NFSP**(待) | self-play diverge in imperfect-info | NFSP avg policy + best-response | 2-3 周 | P2 (主线) |
| **D3 deep CFR redo**(待) | r008 失败是配置问题,deep CFR 范式 OK | r008 重做,neural advantage net | 2 周 | P2 (主线) |
| (skip) D1 belief network | 不适用 — 现有 IS-MCTS 已 Bayesian dice posterior + 已知 card pool | — | 不做 |

## Why D1 belief network 不做(2026-04-28 PM 重新评估)

读 `training/az/determinize.py` 发现:
- ✅ Bayesian Dirichlet posterior 已实现于 `sample_opponent_dice`(α=1 prior + observed payment + tune evidence)
- ✅ Card pool 已知(SharedFixedPool / PerOpponentPool)
- ❌ Opponent policy belief 未建模 → 这是 NFSP 范畴

经典 belief network 在我们设定增量小。"opponent policy belief" = NFSP,合并到 D2。

## Decision tree(sweep 完成后)

| sweep 结果 | 决策 |
|---|---|
| s069/s070/s071 任一 vs F1-D2 ≥ 0.45 | compute/capacity 闭合 -0.27 gap → 推 production scale run |
| s069+s070+s071 都 ≈ 0.27,但 NFSP 或 deep CFR 突破 0.45 | 算法 deficit confirmed,但找到 fix → 推 NFSP/CFR scale |
| 全 sweep ≤ 0.30 | RL 真不可救 → re-confirm closure(ADR-0009 仍有效),最终 close |

## References

- [`adr-0009-rl_paradigm_pivot_terminus.md`](adr-0009-rl_paradigm_pivot_terminus.md)
- [`../5_history/algorithm_sweep_2026_04_28.md`](../5_history/algorithm_sweep_2026_04_28.md)(详细 plan,已归档)
- `docs/5_history/runs_pre_redesign_2026_05_17.md` s068(数据)
- memory `project_algorithm_sweep_2026_04_28`(新 session 起点)

## Verdict

Closure premature。s068 一个 +0.167 数据点已经推翻"完全不可救"的强命题。Sweep 跑完才能下 final closure。
