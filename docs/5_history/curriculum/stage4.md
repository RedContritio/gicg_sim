> **ARCHIVED 2026-05-16(P1-T7)** — Stage 4 ABANDONED per ADR-0009/0010,详见 [`plan.md`](plan.md) 顶部 note。

---

---
stage: 4
status: ABANDONED (curriculum closed at Stage 3 via BC,详见 adr-0009)
last_updated: 2026-04-28
---

# Stage 4 — 加回元素反应

**状态: ABANDONED (2026-04-28).** 不再开启。

理由(详见 [`../../2_decisions/adr-0009-rl_paradigm_pivot_terminus.md`](../../2_decisions/adr-0009-rl_paradigm_pivot_terminus.md)):

- s067 (Stage 3 + 3-card AZ pure self-play, n=3) 实证: 多卡 combinatorial breadth **不让 RL 受益**,反而 vs F1-D2 略降(0.0625 vs s064-066 1-card 0.104)。
- AZ self-play plateau 0.06-0.15 在 5 个 stage 测试上结构性稳定,与 stage 复杂度无关。
- BC alone vs F1-D2 = 0.75 已实质达 Stage 3 stricter PASS;Stage 4 加复杂度只会让 RL 更弱,BC 仍最优。
- Curriculum closed at Stage 3 via BC ckpt;不再推 Stage 4/5。

## Spec (来自 plan.md)

Stage 3 同 + 多元素 char_pool + 元素反应 (火+水=蒸发, +冰=融化 etc.)。仍 1v1。

## Go/No-go (来自 plan.md)

≥ 0.60 vs random。

## 参考

- Plan: [`plan.md`](plan.md) Stage 4 章
