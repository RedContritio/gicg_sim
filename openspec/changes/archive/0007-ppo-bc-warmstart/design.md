# Design (retrospective)

## Consequences

### 实施清单

| 项 | 文件 | 行数估 | 依赖 |
|---|---|---|---|
| 1. teacher 数据生成 | `tools/ppo_gen_bc_data.py` | 150 | framework.matchup.greedy_player, gicg_env |
| 2. BC 训练 loop | `training/ppo/bc_train.py` | 200 | PPONet, data loader |
| 3. TOML config | `configs/s015_bc_pretrain.toml` + `configs/s016_bc_ppo_finetune.toml` | 30+30 | — |
| 4. match rate eval | 融入 bc_train.py 或新 `tools/ppo_bc_eval.py` | 80 | PPONet, GreedyPlayer |
| 5. Launcher | 改 `tools/ppo_launch.py` 支持 BC mode | 50 | — |
| 6. Smoke test | `training/tests/test_ppo_bc_smoke.py` | 80 | — |

**估 1-2 天实现 + 1 天 tune**。

### Registry 三 run 分开登记

- `s015_bc_data_gen` — 生成 50k decisions
- `s016_bc_pretrain` — 吞 s015 data 训 BC 到 match rate 判据
- `s017_bc_ppo_finetune` — 从 s016 ckpt 继续 PPO

一次 gen_bc_data run ≠ 一次 training run;BC data 是 offline dataset 可多次复用。

### 与 r009_plan.md 关系

- r009_plan 设计在 AZ 栈(attention + MCTS)full-game 路径
- 本 ADR 是 PPO 栈 + Stage 1 scope curriculum 路径
- 两者**不冲突,可并行**:r009 → BC + AZ fine-tune,full 2v2 vs mcts_200 ≥ 0.80;本 ADR → BC + PPO
  fine-tune,Stage 1 F1-D2 ≥ 0.40
- 若本 ADR Stage 1 PASS,继续 Stage 2/3 同样 warm-start 路径直到 curriculum 完成;若失败,证明
  "narrow optimal + BC + PPO" 组合也不够,回 AZ 栈路径

## Tradeoffs revisited

| 风险 | Mitigation |
|---|---|
| F1-D2 策略在 PPONet (MLP only) 下 unlearnable | d_model 256→512;再失败加 attention(退 AZ 栈) |
| BC 数据里 teacher 自己也 lose 的局 terminal_z 破坏 value | 过滤 teacher=winner 的决策(只 train 胜局);或不管让 value 学真 MC return |
| PPO fine-tune 第 1 iter 破坏 BC | 低 lr + KL penalty 到 BC policy(`L_kl = KL(π, π_bc)` coef 0.1) |
| Stage 1 下 F1-D2 本身 vs random ~0.X | 跑 `ppo_eval_probe` 看 F1-D2 真实 wr,若 <0.8 换 teacher (F1-D3?) |

### 待确认决策点

1. **Teacher hard vs soft target** — 建议先 hard,failed 再上 soft(soft 需改 `GreedyPlayer.select_action`
   暴露 scores)
2. **BC pretrain 阶段 value head 训不训** — 建议训(MC terminal_z,可能有偏但 PPO fine-tune 需要 value
   init;风险#2 方案 2 "不管,让 value 学真 MC return")
3. **fine-tune 加 KL penalty 不** — 建议不加,用 lr=1e-4 保守

## 后续 closure 命中

参见 [`../0009-rl-paradigm-pivot-terminus/`](../0009-rl-paradigm-pivot-terminus/):BC warm-start
整体范式(含本 ADR 描述的 PPO 路径)被 closure。本 ADR 描述的实施细节作为历史保留,LOC / config /
score 数据进 `docs/4_runs/registry.md` s064-066 / r009-r012。

## References

- `docs/2_decisions/adr-0007-ppo_bc_warmstart.md` (mirror)
- `../0008-rl-paradigm-pivot/` — 前置 paradigm 转向
- `../0009-rl-paradigm-pivot-terminus/` — 后续 closure
- `docs/4_runs/_individual/r009_plan.md` — AZ 路径平行计划
- `training/ppo/net.py::PPONet` — 复用网络
- `training/ppo/bc_train.py` — shipped BC 训练 loop
