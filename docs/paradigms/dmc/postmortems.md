---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# DMC postmortems

> ⚠ DMC paradigm 仍 **ACTIVE**,Stage 3 GPU train pending — 真正 paradigm-level
> postmortem 暂无。本 dossier 只列**已落盘的 critique / review**(`dmc_review.md`)
> + 待 closure 决策的 open items。

## 主要 review / critique 来源

| Topic | Canonical doc |
|---|---|
| 41 项 critique(5/14)| [`docs/5_history/reviews/dmc_review.md`](../../5_history/reviews/dmc_review.md) |
| Phase 3.5 infra refactor design | [`docs/5_history/dmc_phase35_infra.md`](../../5_history/dmc_phase35_infra.md) |
| Phase 3.5 infra impl sub-plan | [`docs/5_history/dmc_phase35_infra_impl/`](../../5_history/dmc_phase35_infra_impl/) |
| LIVE working notes | [`training/paradigms/dmc/notes.md`](../../../training/paradigms/dmc/notes.md) — **不复制,只 link** |

## dmc_review.md 41 项 critique 分组摘要

> Full text → [`docs/5_history/reviews/dmc_review.md`](../../5_history/reviews/dmc_review.md)。
> 本 dossier 仅列 paradigm-level 高优先级 critique。

### A 组(6 项)— paradigm 与 GICG task structure 错配

- **A.3**(最危险):Stage 3 PASS WP ≥ 0.50 vs **同 setup 实测 RL 上限 0.271 ± 0.078**
  (AZ s068 D4 asymmetric 3 seed)。立项即过乐观;Stage 3 GPU train 若 FAIL,需
  closure 决策:接受 paradigm closure 还是降 PASS 阈值。
- DouZero 成功条件(action 空间大但 well-defined / 严格回合制 / 显式 trick 信息)
  在 GICG 上几乎不成立 — A.1-A.6 详 review。

### B 组(4 项)— "复用 AZ ActorCritic" 代价被低估

ADR-0006 三层 layout(framework / az / cfr 零互 import)实质被破坏 — DMC 用
AZ ActorCritic 但 logit-as-Q 改 head 语义,decision A1 50 LOC vs 重写 300 LOC 的
账 underestimate。

### C 组(14 项)— shipped 代码 hard bug + 静默 correctness 问题

至少 4 hard bug + 多项静默 correctness。Phase 3.5 NaN guard 修了一项
(loss=NaN → weights NaN → argmax 永远 0),其他需逐项 cross-check Phase 3.5 commit
chain 是否 fix。

### D 组(5 项)— eval 协议自身 noise dominated

Phase 3.4 PASS 是过度乐观解读 — n=128 swap eval 在 paradigm 早期 frame count 下
WP 0 → 0.125 directional only,**not** robust PASS signal。

### E 组(5 项)— Stage 3 cfg 算力账目至少差 1-2 个数量级

GPU 资源会大量浪费。Phase 3.4.5 CPU profile 是这部分的 mitigation,但未做完。

### F 组(7 项)— fallback / ablation / 诊断预算不存在,closure 决策未引用

DMC 决策没有引用 ADR-0009 / ADR-0010 closure 集合(即 PPO / AZ 已尝试的 lever)。
若 Stage 3 FAIL,缺乏 paradigm-level 退路 plan。

## Closure decision pending

Stage 3 GPU train 是 paradigm-level go/no-go。3 个可能 outcome:

1. **PASS WP ≥ 0.50 vs F1-D2**:DMC paradigm ACCEPT,落 ADR(paradigm-dmc capability spec
   per `openspec/specs/paradigm-<name>/`)。
2. **FAIL WP < 0.30**:接受 paradigm closure,加入 ADR-0009/0010 集合;BC ckpt 仍
   作 production fallback。
3. **0.30 ≤ WP < 0.50**:partial — 类似 AZ s068 D4(0.271)的 partial reopen 处境,
   需 user 决策是否切换 stage / lever 继续。

## 不复制 LIVE working notes 的理由

`training/paradigms/dmc/notes.md` 是 working notes(实时更新 + decision changelog + Phase 进度)。
本 dossier 是 paradigm-level 历史复盘入口,**不 mirror LIVE 内容** — 避免维护漂移。
读者要看实时进度 → 直接读 LIVE notes;要看 paradigm-level verdict / 历史观察 → 读本 dossier。

## DMC vs AZ/PPO 关键对比(paradigm-level)

| 维度 | PPO | AZ | DMC |
|---|---|---|---|
| Stage 3 1-card F1-D2 ceiling | 0.344(BC+PPO best,n=3) | 0.271(s068 D4 best,n=3)| TBD(Phase 3.4 directional 0.125;Stage 3 GPU train 验证)|
| BC warm-start lever | +0.24 dominant | +0.063(destruction)| N/A(无 BC init 路径,decision 未提)|
| Architecture iteration | shared trunk(无 paradigm-specific iter)| C1v0-v7 7 iter | reuse AZ ActorCritic + logit-as-Q(A1) |
| Compute | 30+ ablation × n=3,~120 GPU-h total | ~80 GPU-h total | Stage 3 alone ~25-40 GPU-h |
| Closure status | CLOSED ADR-0009 | CLOSED ADR-0009 / partial reopen ADR-0010 | ACTIVE — Stage 3 pending |

## Follow-up SHOULDs

1. Stage 3 GPU train 启动前 register r013 行 in [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)
2. Phase 3.5 commit chain 与 `dmc_review.md` C 组逐项 cross-check,确认哪些 bug 已 fix
3. Stage 3 GPU train 结果出来后落 ADR(PASS → paradigm-dmc spec;FAIL → closure ADR)
4. A.3 PASS 阈值 0.50 复议(基于 PPO/AZ 实测上限 0.27-0.34)
