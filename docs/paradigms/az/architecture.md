---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# AZ architecture evolution

> 完整网络架构演化(C1v0-v7)+ 6 hook gradient bug 修复见
> [`docs/5_history/network_design_history.md`](../../5_history/network_design_history.md)
> (canonical source,本 dossier 不复制)。本文给 paradigm-level 概览 + 关键决策路径。

## C1 family timeline

| Version | Date | Key change | Outcome |
|---|---|---|---|
| C1v0 | 2026-04-09 | 初始 IS-MCTS + actor-critic + cross-attn,team_size=1 mirror | ID-leak 嫌疑;vs random ≤ 50% |
| C1v1 | 2026-04-10 ~ 12 | 网络 value 直接做 MCTS leaf eval | C1 失败诊断起点 — net 不准时反而拉低 search 质量,详 memory `project_c1_failure_diagnosis` |
| C1v2 | 2026-04-13 | lambda=0 rollout 训练验证(纯 MCTS rollout 不掺 net value) | vs mcts_200 = 50%(C1v1 的 10×);recover 假设确认 |
| C1v3 | 2026-04-14 ~ 15 | lambda=0.3 混合 anneal + 部分修复 | 仍弱;value head signal 质量是 bottleneck |
| C1v4 | 2026-04-16 | 进行中 → C1v5 单变量调参 / 不再扩 | 详 memory `project_c1v4_status` |
| C1v5/v6 | 2026-04-17 | **6 项 hook gradient bug 修复**(详 5_history c1v6_plan)| ⚠ F 前所有 ckpt 作废;后续 run 是修复后的 |
| **C1v7** | **2026-04-18** | **struct_readout + sid pinning** | **反 ID 首次公平验证 PASS,argmax vs mcts_200 = 0.45**,详 memory `project_c1v7_success` |

## Critical fixes(6 项 hook gradient bug)

详 [`docs/5_history/postmortems/c1v6_plan.md`](../../5_history/postmortems/c1v6_plan.md)
+ [`docs/5_history/network_design_history.md`](../../5_history/network_design_history.md)
§ Gradient bug。简要列:

1. Hook gradient — autograd 沿 hook chain 错传(无 detach 导致 cross-skill 污染)
2. CrossAttention 满熵(pool 零空间 C18 定理;C1v7 struct_readout 绕过)
3. Hook owner obs gap(commit 3c2ee89 加 char_skill_refs 区 + SkillSlotPerm)
4. team_size scaling cost(team_size 1→2 使 n_steps×3.3,每局慢 5×;disjoint_teams=True 防 #152 双注册)
5. Mirror match hook bug #152(DSL filter + B-plan talent 修复)
6. Stale weights tolerance(AZ async stale weight 不影响收敛 — `feedback_stale_weights_ok`)

每个修复都附 reproducer / regression test。

## Paradigm-level 决策路径

```
C1v0 (initial)
  └── ID-leak suspicion → C1v1 IS-MCTS migration
C1v1 (net-as-leaf root cause discovered)
  └── lambda=0 rollout fallback → C1v2
C1v2 (validation 50% vs mcts_200)
  └── lambda anneal restore → C1v3-v4
C1v4 (status quo) — D-series decisions kick in (D1-D14):
  ├── D2 state-aware hook attention (OBSOLETE — C1v7 struct_readout 取代)
  ├── D4 mirror-break (later s068 probe)
  ├── ExpandUnionK (later removed via ADR — net negative)
  └── 6 hook gradient bug 修复 → C1v6
C1v7 (struct_readout + sid pinning) — paradigm-anchor
  └── 反 ID 公平验证 PASS argmax vs mcts_200 = 0.45
```

D-series 决策(D1-D14)落 [`openspec/changes/archive/0005-az-decisions-d1-d14/`](../../../openspec/changes/archive/0005-az-decisions-d1-d14/)。

## 被绕过 / 推翻的设计假设

| 假设 | 验证 | 结论 |
|---|---|---|
| Network value 做 MCTS leaf 是 AlphaZero 标准 | C1v1 vs mcts_200 ≤ 0.05 | net 质量不够时拉低 search;改 lambda 混合 anneal |
| State-aware hook attention(D2)修 hook gradient | C1v6 ckpt 仍弱 | C1v7 struct_readout 用 pool 零空间绕过,attention 不再是必需 |
| CrossAttention 满熵 = pool 零空间病理 → 必须 attn supervision | C1v7 struct_readout 直接绕过 | 不引入 attn supervision,绕过更简洁 |
| ExpandUnionK(K=3 扩 dice variant)提升 search 深度 | r003-r005A K=3 净负 0.05 | ADR 移除;只变 dice 不变 hand/deck 覆盖率 < 20% |
| BC warm-start 对 AZ 同样 dominant | r010 F1-D2 = 0.167(vs PPO BC+PPO 0.500) | **AZ training destroys BC signal**,paradigm-dependent |
| Mirror Nash 锁死是 Stage 3 plateau 唯一主因 | s068 D4 asymmetric +0.167 | partial 主因(并非唯一);ADR-0010 reopen |

## Search engine

AZ 搜索引擎是 [`gicg_mcts/`](../../../gicg_mcts/)(Go IS-MCTS L3:tree + PUCT + backup)。
Engine 演化记录:[`docs/5_history/search_history.md`](../../5_history/search_history.md)。
Network ↔ MCTS 协议(determinize / cancel / parallel rollout)落
[`openspec/specs/search-{ismcts,parallel}/`](../../../openspec/specs/) capability spec。

## Code

- 历史 `training/paradigms/az/legacy/network/` 已退役；当前共享网络位于
  [`training/core/network/`](../../../training/core/network/)
- 历史 `training/paradigms/az/legacy/mcts/` 已退役；当前 Python MCTS 位于
  [`training/paradigms/az/mcts/`](../../../training/paradigms/az/mcts/)（action_id /
  node / parallel / rollout / search)
- [`training/paradigms/az/selfplay.py`](../../../training/paradigms/az/selfplay.py) — self-play loop 的现行位置
- [`gicg_mcts/`](../../../gicg_mcts/) — Go MCTS L3
