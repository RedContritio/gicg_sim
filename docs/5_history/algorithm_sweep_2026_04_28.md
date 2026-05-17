> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **STALLED → SUPERSEDED**
> - 2026-04-28 PM 启动 sweep(s069 compute probe / s070-071 conditional / D2 NFSP / D3 deep CFR redo)
> - s069 18+ days `pending`,实际 cancelled(per memory `project_algorithm_sweep_2026_04_28` user-killed at seed42)
> - 2026-05-12 起 DMC paradigm pivot(`training/dmc/`)take over,本 sweep plan **superseded**
> - Latest decision:`memory project_rl_routes_closure_2026_05_12`(user-evaluated closure 比 docs documented 更广)
>
> 后续 RL paradigm 推进见 `openspec/specs/training-architecture/`(P2 unified-training-pipeline change)。

---

---
plan: algorithm_sweep_2026_04_28
status: ACTIVE
last_updated: 2026-04-28 PM
---

# Algorithm Sweep — closure 部分推翻后的 RL 探索

## 背景

ADR-0009(2026-04-28 AM)closure self-play RL 在 GICG 不可救。下午 s068 D4 mirror-break probe(asymmetric teams)给 +0.167 vs s064-066 mirror baseline → **closure 部分推翻**(adr-0010)。

## 关键 sweep 数据

| 维度 | s064-066 (mirror baseline) | s068 (asymmetric) | F1-D2 vs F1-D2 control(asymmetric) |
|---|---|---|---|
| F1-D2 mean ± std | 0.104 ± 0.072 | **0.271 ± 0.078** | **0.54** |

s068 改善 +0.167 显著(>2σ),但仍 -0.27 below F1-D2 baseline。**剩 50% 故事**。

## Sweep 矩阵

### 已完成

- s064-066 mirror Stage 3 1-card AZ pure (n=3): F1-D2=0.104
- s067 Stage 3 + 3-card mirror AZ pure (n=3): F1-D2=0.0625
- r010-012 Stage 3 1-card mirror AZ + BC (n=3): F1-D2=0.167
- **s068** Stage 3 1-card asymmetric AZ pure (n=3): **F1-D2=0.271**

### 在跑

- **s069** (14:21 启动): compute probe — s068 spec + n_rollouts 100→500
  - ETA ~5h
  - Decision: F1-D2 ≥ 0.45 闭合 → compute 是问题 / ≈ 0.25-0.35 → 算法 deficit

### 计划

| ID | 假设 | 配置 changes | 工作量 |
|---|---|---|---|
| s070 | training 不够 | s068 spec + n_games 200→1000 | 5h, conditional on s069 |
| s071 | capacity 不够 | s068 spec + d_model 128→256 | 2h |
| D2 NFSP | self-play diverge | new: avg policy + best-response | 2-3 周 |
| D3 deep CFR | imperfect-info NE | r008 redo with neural advantage | 2 周 |

## Decision tree

```
s069 verdict
├── F1-D2 ≥ 0.45 (闭合 -0.27 gap 半数+)
│   └── compute 是问题 → s070 longer training,看是否进一步闭合
│       └── 闭合 → production scale run
│       └── plateau → diminishing returns,explore 算法
└── F1-D2 < 0.40 (没闭合)
    └── compute 不是 → s071 capacity probe(d_model=256)
        ├── F1-D2 ≥ 0.40 → capacity 是问题 → scale architecture
        └── F1-D2 ≈ 0.27 → 算法 deficit 确认 → D2 NFSP / D3 deep CFR
```

## 主算法 fix 候选(若 sweep S5 cheap probes 都不够)

### D2 NFSP(2-3 周,理论最强)

NFSP (Heinrich & Silver 2016) 经典:vanilla self-play RL 在 imperfect-info 必 diverge,需要:
- Average policy network(supervised on best-response data)
- Best-response RL with reservoir buffer
- ε-fictitious play schedule

**实现要点**:
- 双 network 架构(avg policy + best response)
- Reservoir buffer 存 best-response action 数据
- Schedule:η% 时间 best-response training,(1−η)% avg policy training

**预期**:NFSP avg policy 不会被 self-play diverge 摧毁(理论保 NE 收敛),应避免 r010 BC 0.75 → 0.17 现象。

### D3 deep CFR redo(2 周,基于 r008 infra)

r008 OS-MCCFR 失败原因:mirror match + ckpt 选择 + advantage_reset 缺失。

**修复**:
- per-iter gauntlet(early ckpt 比 late ckpt 强这种现象 visible)
- advantage_reset_each_iter=True
- d_model=64→128(r008 用 64 太小,容量可能也是问题)
- AlphaHoldem (2022) 范式参考

**预期**:r008 iter 20=1.0 那个早期 ckpt 给信号,deep CFR 范式可能 work,只是 r008 配置 bad。

## Production fallback

**若全 sweep 失败**(s069/s070/s071/D2 NFSP/D3 deep CFR 都 ≤ 0.30):
- production = r009 BC ckpt epoch_3 (vs F1-D2 = 0.75)
- final closure(ADR-0009 仍有效)
- write final paper / closure doc

## 总时间估算

cheap probes (s069+s071): ~7h(s069 在跑)
mainline algorithm work (D2 NFSP + D3 deep CFR): ~4-5 周

**完整 sweep ETA**: 5-6 周 wallclock

## 新 session 接力指南

新 session 起来时先读:
1. `docs/0_status/README.md` - 当前 phase
2. memory `project_algorithm_sweep_2026_04_28` - 详细 sweep 状态
3. 本文件(plan)
4. `pgrep -fl multi_seed_launch` - 看是否有训练在跑
5. 按上面 decision tree 判断下一步
