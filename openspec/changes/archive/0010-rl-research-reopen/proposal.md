# RL research reopened — closure 部分推翻,跑 algorithm sweep 至 final verdict

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0010-rl_research_reopen.md` at P1-T1)
**Original date:** 2026-04-28 PM(同日下午)
**Original status:** Accepted
**Supersedes:** Partially supersedes [`../0009-rl-paradigm-pivot-terminus/`](../0009-rl-paradigm-pivot-terminus/)
— 同日 AM closure 命题部分推翻。production fallback decision 不变(仍 r009 BC ckpt)。
**Superseded by:** —

## Why

ADR-0009 上午基于 PPO/AZ/AZ+BC 三栈 × 5 stage = 15 数据点全失败,closure self-play RL。下午 s068 D4
mirror-break probe(asymmetric teams 赤蝶 vs 墨客,Stage 3 1-card)给:

- F1-D2 mean = **0.271 ± 0.078** (n=3)
- vs s064-066 mirror baseline 0.104:**+0.167 显著超 noise (>2σ)**

意味着 mirror Nash 锁死**部分**贡献了 RL plateau。closure "RL 在本游戏类不可救" 命题**被部分推翻**。

## What

1. **Reopen RL research**:跑完所有候选 algorithm fix,直到全部失败才 final closure
2. **保留 ADR-0009 作为 closure 的初始判断**(基于当时数据合理),本 ADR 作为后续 update
3. **Production fallback 不变**:r009 BC ckpt epoch_3 (vs F1-D2 = 0.75) — 若 sweep 全 fail,closure 仍生效

### Algorithm sweep plan

| ID | 假设 | 配置 | 工作量 | 优先级 |
|---|---|---|---|---|
| **s069 (running 14:21)** | compute deficit | s068 spec + n_rollouts 100→500 | 5h | P0 |
| s070 (待) | training duration 不够 | s068 spec + n_games 200→1000 | 5h | P1, conditional |
| s071 (待) | capacity 不够 | s068 spec + d_model 128→256 | 2h | P1 |
| **D2 NFSP** (待) | self-play diverge in imperfect-info | NFSP avg policy + best-response | 2-3 周 | P2 (主线) |
| **D3 deep CFR redo** (待) | r008 失败是配置问题,deep CFR 范式 OK | r008 重做,neural advantage net | 2 周 | P2 (主线) |
| (skip) D1 belief network | 不适用 — 现有 IS-MCTS 已 Bayesian dice posterior + 已知 card pool | — | 不做 |

## Affected specs

- `paradigm-az` (sweep 继续)
- `paradigm-cfr` (D3 deep CFR redo 候选)
- `paradigm-nfsp` (D2 NFSP 候选)
