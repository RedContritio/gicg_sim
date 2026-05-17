> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **CLOSED** by ADR-0009 / ADR-0010. 整目录归档,详见 [`plan.md`](plan.md) 顶部 note。

---

---
last_updated: 2026-04-26
---

# 3_plans/curriculum/ — RL Curriculum 主线

> RL 可学性验证的主路线。5-stage 渐进 (1v1 最简 → full 2v2)。
> 每 stage 有独立 status doc;所有 stage 共享 [`plan.md`](plan.md) 主规范。

## Stage 状态总览 (PPO + AZ 双栈)

| Stage | PPO F1-D2 | AZ F1-D2 (n=3) | AZ vs random (n=3) | Doc |
|---|---|---|---|---|
| 0 | 0.875 (s008) | 0.125 ± 0.000 (s055-57) | 0.917 ± 0.072 | [stage0](stage0.md) |
| 1 | 0.500 (s017 BC→PPO) | 0.125 ± 0.000 (s058-60) | 0.938 ± 0.063 | [stage1](stage1.md) |
| 2 | 0.531 (s020 BC→PPO) | 0.146 ± 0.036 (s061-63) | 0.917 ± 0.072 | [stage2](stage2.md) |
| 3 | 0.34 ceiling (1-card fullobs best) | **0.104 ± 0.072 (s064-66)** | 0.833 ± 0.130 | [stage3](stage3.md) |
| 4 | — | pending | — | [stage4](stage4.md) |
| 5 | — | pending | — | [stage5](stage5.md) |

**关键发现 (2026-04-26):** AZ pure self-play 在弱 baseline (vs random) 表现强,但 vs F1-D2 plateau ≈ 0.125 跨 Stage 0/1/2 不变,与 PPO pure-PPO Stage 1 同水平。Mirror match self-play collapse 是结构性问题,与 stage 难度无关。突破需 BC warm-start 或其他机制。

## 当前决策窗口

Stage 3 PPO closure 后,下一动是 AZ 路线 (α/β/γ 选项)。详见
[`../../0_status/README.md`](../../0_status/README.md) 和
[`../az/r009_az_warmstart.md`](../az/r009_az_warmstart.md)。

## 编辑

- 每 stage doc 是 LIVE,跑完 update + 翻 status
- closure 后的 stage,详细 ablation 数据沉淀到 `5_history/ablations/`,本 doc 留摘要
