# DMC · Deep Monte Carlo for GICG

> Paradigm transferred from DouZero (ICML 2021, repro at `~/Projects/Research/douzero_icml2021/`)
> 与 `training/az/` 和 `training/cfr/` 同级, 共用 `training/framework/`(零互 import,符合 ADR-0006 layout)

## 选择 DMC 的理由

`~/Projects/Research/douzero_icml2021/` Phase 0/1/2 实证(2026-05-12 → 13):

- Phase 0:DouZero-WP pretrained vs SL Landlord WP 0.551(paper 0.5692,-3.2%)
- Phase 2:scaled-down(2e9 frames / 1× H20 / 16.5h)Landlord vs SL WP **0.5236 ± 0.0047 (5-seed)**,paper -8.0% gap
- DMC paradigm 在 imperfect-info + sparse terminal + 大 action space 上 work 已 verified

GICG 同类 task structure:
- ✅ Imperfect-info(POSG with hidden hand/dice/deck)
- ✅ Sparse ±1 terminal reward
- ✅ 大 action space(~100-300 legal/turn)
- ✅ Asymmetric matchup(default 双方异构)
- + GICG 特有维度:multi-char switch active / 7-color dice + tune / element reactions

DMC 在 GICG 上的 verify 是 user 目标 "zero-shot RL + ≥ greedy" 的核心 paradigm 测试。

## 目标 — 3 Stage 渐进 verify

| Stage | Setup | PASS criteria | 对照 baseline |
|---|---|---|---|
| **3** | 1 char asymmetric(team_0=赤蝶, team_1=墨客 类似 s068)+ `[测试卡_增幅, 测试卡_碎片]` + obs_mask + random dice + max_rounds=5 | **vs F1-D2 WP ≥ 0.50** | s068 AZ pure asymmetric **0.271 ± 0.078** → DMC 需 +0.23 |
| **4** | 每局 random sample team_size ∈ {1,2,3}(双方相同)+ asymmetric char selection + 沿用 stage 3 deck + 元素反应自然 active | **vs F1-D2 WP ≥ 0.50** | 无 PPO/AZ baseline |
| **5** | 3 char asymmetric + v_phase2 full deferred deck(含 status / summon / multi-turn buff) | **vs F1-D2 WP ≥ 0.50** | 无 baseline |

Stage 3 是 *paradigm-task fit 决定性测试*(突破已 documented closure)。Stage 4 是 user 目标 floor。Stage 5 是 user 终极目标(需 v_phase2 deferred Batch 1-2 task realism 前置)。

## Decision 表(全 settled,详细论证见 PLAN.md)

| # | 决策点 | 选项 |
|---|---|---|
| 1 | Q-network | **A1**:复用 `training/az/network/actor_critic.py` logit-as-Q,改训练 loss 即可 |
| 2 | Action encoding | hook_emb gather(GICG 现有 DSL token 表示,inherit zero-shot)|
| 3 | Shared network | single shared(双方对称 perspective flag distinguish) |
| 4 | Opponent mix | **30% random + 30% F1-D2 + 10% F1-D4 + 30% historical**(ring K=20)|
| 5 | Stage 划分 | 3 stages,skip 0-2(已 PPO/AZ PASS),no mirror,no explicit "reactions" stage |
| 6 | Cross-platform | **9950X3D Windows native + libgicg.dll**(Mac dev .dylib + Linux H20 .so + Windows .dll 三平台 platform-detect)+ TCP localhost(替换 Unix socket) |
| 7 | 目录 | `gicg_mono/training/dmc/`(in-repo,与 az / cfr 同级)|
| 8 | Eval 协议 | **lazy periodic**: 每 1 wall-h eval n=128 + swap_sides + fixed seed scenarios,只测 F1-D2 + F1-D4,metrics.jsonl |
| 9 | CPU 充分优化 | per-actor `OMP_NUM_THREADS=1` + `torch.set_num_threads(1)` + `torch.inference_mode()` + JIT trace inference + `psutil.cpu_affinity` 把 actor 钉到 X3D CCD0(V-Cache)+ shared memory replay buffer。Target per-actor 1500-1800 fps(类比 DouZero phase 2 X3D 预估) |
| 10 | 训练监控 | **TensorBoard** via `torch.utils.tensorboard.SummaryWriter`,写 `artifacts/<run>/tb/`。12 个 scalar tag:`train/{loss,grad_norm,fps}` + `episode/{return_G,return_mean100,win_rate_100,n_steps,buf_size}` + `eval/{F1-D2_wp_mean,wp_swap_p0,wp_swap_p1,ci95_width}`。查看:`tensorboard --logdir artifacts/<run>/tb` |

## Layout

```
training/dmc/
├── README.md      # 本文 — 总览 + decision + status
├── PLAN.md        # Phase-by-Phase step-by-step
├── notes.md       # 运行观察 + decision changelog
├── __init__.py
├── config_loader.py  # DmcConfig(类比 training/az/config_loader.py)
├── loss.py        # MC return + MSE on logit-as-Q
├── replay.py      # (state, action_idx, episode_return) schema
├── agent.py       # DMC inference agent(argmax over logits,ε-greedy 0.01)
├── train_loop.py  # actor-learner async loop
├── opponent_pool.py  # mixed opponent pool(random + F1-D2 + F1-D4 + historical ring)
└── eval/
    ├── gen_eval_scenarios.py  # fixed seed scenario pre-gen
    └── periodic_eval.py        # in-training eval thread
```

## Status

- **2026-05-12** 设计落定,3 docs draft 完成。
- (待办)Phase 3.1+:implementation 开工

每 Phase 完成更新本节。详细 step 见 [PLAN.md](PLAN.md)。

## 关键 reference

- DouZero paper: <https://arxiv.org/abs/2106.06135>
- DouZero repro 结果: `~/Projects/Research/douzero_icml2021/notes.md` + `phase2_report.md`
- DouZero `dmc/` source: `~/Projects/Research/douzero_icml2021/original/DouZero/douzero/dmc/`
- GICG s068 baseline: `docs/5_history/runs_pre_redesign_2026_05_17.md` (s068 mirror-break 3 seeds)
- GICG F1-D2 反例: `tools/test_dice_scheduling.py` (historical, archive-removed 2026-05; 4 documented scenarios, gap 2-6 damage — see commit history)
- ADR-0006 training layout: `docs/2_decisions/adr-0006-training_layout.md`
