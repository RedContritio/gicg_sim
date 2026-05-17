# PPO BC warm-start 设计

> **MOVED to `openspec/changes/archive/0007-ppo-bc-warmstart/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0007-ppo-bc-warmstart/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0007-ppo-bc-warmstart/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**日期:** 2026-04-25
**前置:** `adr-0008-rl_paradigm_pivot.md` + s009-s014 6 run 穷举证实 Stage 1 pure PPO structural 不行
**paradigm:** 本文是 `../4_runs/_individual/r009_plan.md`(AZ 路径)到 **PPO 路径**的 adaptation

---

## 目标

用 F1-D2 dice_greedy 作 teacher,BC 预训 `PPONet`,然后 PPO fine-tune,在 Stage 1 上
达成 vs F1-D2 ≥ 0.40(Stage 1 Go/No-go)。

和 r009_plan 的关键区别:
- **stack**: PPO (当前 curriculum 栈),不是 AZ
- **network**: `training/ppo/net.py::PPONet`(MLP trunk + policy/value 双头),不是 AZ 的
  `training/az/network/Agent`(含 attention/struct_readout 等)
- **fine-tune**: PPO clip loss,不是 AZ MCTS
- **scope**: Stage 1(随机骰),不是 full 2v2

**不追求超过 F1-D2** — 这和 r009 一样只是 warm-start。PPO fine-tune 的目标是从
F1-D2 ceiling (vs F1-D2 ~0.50) 突破到 > 0.60。

---

## 关键设计决策

### 1. Teacher trajectory collection

**teacher 策略:** F1-D2 + dice_greedy(和 r009 一致,s007 验证最强 greedy)

**Rollout setup** — 两种起点,每局随机选:
- **F1-D2 self-play**(50%): 双方都用 F1-D2,只记录 "当局随机挑的一侧" teacher decisions
- **F1-D2 vs F1-D1**(50%): F1-D2 作 teacher 记,对手 F1-D1 产生不同棋局(不记对手决策)

避免 100% self-play 下轨迹过度确定的问题(r009 plan §2)。

**每局 seed 独立**,fix_dice=None(Stage 1 spec),max_rounds=3。

**每 teacher 决策记录:**
```python
{
    'obs': ndarray[obs_size],          # 即 PPO 的 dynamic obs
    'legal_mask': ndarray[max_actions], # bool
    'action': int,                      # teacher argmax index
    # 可选(若后续需要 soft label):
    # 'teacher_scores': ndarray[max_actions],  # F1-D2 raw scores
    'terminal_z': float,                # ±1 / 0 (draw), 该局最终结果,从 teacher 视角
}
```

**存储:** 一个大 `npz` 文件,所有 decisions concat 成 flat arrays。
位置 `artifacts/<ts>_s015_bc_data/dataset.npz`。

**数据量:** 目标 50k teacher decisions。
估算:
- Stage 1 每局 ~30-40 teacher decisions(teacher 仅控一侧)
- 50k / 30 ≈ 1700 局
- F1-D2 每局 ~0.9s(s012 ladder 测)+ swap overhead ≈ 1.5s/局
- **1700 × 1.5s ≈ 42 min wall time** — 一个 smoke-scale 跑完

### 2. 网络: 复用 PPONet, d_model 不动

`training/ppo/net.py::PPONet` d_model=256,trunk 2 层 MLP,policy/value 双头。

**不改结构**。先用当前 PPONet 做 baseline,看 BC match rate。若 < 60% 再考虑加大
d_model / 加层数。

### 3. BC loss

**policy head:** cross-entropy to teacher argmax,legal_mask 应用到 logits:
```python
logits, value = net(obs)             # logits[max_actions], value[1]
masked = logits.masked_fill(~legal_mask, -inf)
logp = F.log_softmax(masked, dim=-1)
L_policy = F.nll_loss(logp, teacher_action)  # CE
```

**value head:** 虽然 BC 主要是训 policy,value head 也要训(后续 PPO fine-tune 会用):
```python
L_value = F.mse_loss(value, terminal_z)
```

其中 `terminal_z` 是该 decision 所在 episode 的最终结果(teacher 视角 ±1 / 0)。
MC estimate,不做 TD bootstrap(BC 阶段没 reward trajectory)。

**total:**
```
L_total = L_policy + value_coef * L_value
value_coef = 0.1  # 和 PPO 现 default 一致
```

**Legal mask 处理:** 仅 legal action 参与 softmax,CE 计算不受 illegal logits 影响。

### 4. BC pretrain 超参

- Optimizer: Adam
- LR: 3e-4(PPO 同值,过渡无缝)
- Batch: 256
- Epochs: 10(100k steps 估算:50k decisions × 10 epochs / batch 256 ≈ 2000 updates)
- LR schedule: linear decay 到 3e-5
- Grad clip: max_norm=0.5(PPO 同值)

### 5. PPO fine-tune 衔接

BC 完成后,**直接用 PPO train loop 继续**,但:
- 加载 BC ckpt 的 `state_dict`(policy + value 都 init 好)
- **降低 entropy_coef**: 0.01 → 0.003(BC 已 commit 到 teacher distribution,太多 entropy
  会破坏 commitment)
- **降低 lr**: 3e-4 → 1e-4(防止 warm-start 被早期 PPO gradient 冲掉)
- **rollout_opponent**: 'F1-D1,F1-D2' mix(s014 setup)
- **n_iterations**: 500-1000(不需要 2000,因为起点已强)

### 6. Go / No-go 判据

BC 阶段(在 held-out 100 局 teacher decisions 上):
- **match rate ≥ 80%**: ✓ 进 PPO fine-tune
- match rate 60-80%: 加大 d_model 或加数据
- match rate < 60%: 停,诊断 obs/网络缺陷

PPO fine-tune 阶段(vs F1-D2, n=64):
- **≥ 0.40**: Stage 1 Go/No-go PASS,推进 Stage 2
- 0.25-0.40: MARGINAL,加 iter
- < 0.25: fine-tune 破坏了 BC,调 lr / entropy / KL penalty

---

## 实施清单

| 项 | 文件 | 行数估 | 依赖 |
|---|---|---|---|
| 1. teacher 数据生成 | `tools/ppo_gen_bc_data.py` | 150 | framework.matchup.greedy_player, gicg_env |
| 2. BC 训练 loop | `training/ppo/bc_train.py` | 200 | PPONet, data loader |
| 3. TOML config | `configs/s015_bc_pretrain.toml` + `configs/s016_bc_ppo_finetune.toml` | 30+30 | — |
| 4. match rate eval | 融入 bc_train.py 或新 `tools/ppo_bc_eval.py` | 80 | PPONet, GreedyPlayer |
| 5. Launcher | 改 `tools/ppo_launch.py` 支持 BC mode(或新 `tools/ppo_bc_launch.py`) | 50 | — |
| 6. Smoke test | `training/tests/test_ppo_bc_smoke.py` | 80 | — |

**估 1-2 天实现 + 1 天 tune。**

---

## 与 r009_plan.md 的关系

r009_plan 设计在 AZ 栈(attention + MCTS),是 full-game 路径。本文档是 PPO 栈 + Stage 1
scope,是 curriculum 路径。两者**不冲突,可并行**:
- r009 完成 → BC warm-start + AZ fine-tune,目标 vs mcts_200 ≥ 0.80 on full 2v2
- 本文档完成 → BC warm-start + PPO fine-tune,目标 Stage 1 F1-D2 ≥ 0.40

若本文档在 Stage 1 PASS,继续 Stage 2/3 同样 warm-start 路径直到 curriculum 完成;
若失败,证明"narrow optimal + BC + PPO" 组合也不够,回 AZ 栈路径。

---

## 数据存储注意

**一次 gen_bc_data run ≠ 一次 training run**。BC data 是 offline dataset,可多次复用。

Registry 登记:
- `s015_bc_data_gen`(pending/done) — 生成 50k decisions
- `s016_bc_pretrain`(pending) — 吞 s015 data,训 BC 到 match rate 判据
- `s017_bc_ppo_finetune`(pending) — 从 s016 ckpt 继续 PPO

三个 run 分开登记,便于 debug 和 reuse。

---

## 风险

| 风险 | Mitigation |
|---|---|
| F1-D2 策略在 PPONet(MLP only)下 unlearnable | d_model 256→512;再失败加 attention(退回 AZ 栈) |
| BC 数据里 teacher 自己也 lose 的局 terminal_z 破坏 value | 过滤 teacher=winner 的决策(只 train 胜局);或不管,让 value 学真 MC return |
| PPO fine-tune 第 1 iter 破坏 BC | 低 lr + KL penalty 到 BC policy(`L_kl = KL(π, π_bc)`,coef 0.1) |
| Stage 1 下 F1-D2 本身 vs random ~0.X(teacher 自己不够强) | 跑 `ppo_eval_probe` 于 Stage 1 env 看 F1-D2 真实 wr,若 <0.8 换 teacher(F1-D3?) |

---

## 等待确认的决策点

1. **teacher 要不要用 soft target(scores + T=0.5 softmax)还是 hard argmax?**
   - soft 更 informative 但需改 `GreedyPlayer.select_action` 暴露 scores
   - 建议先 hard,failed 再上 soft
2. **BC pretrain 阶段 value head 训不训?**
   - 训:MC terminal_z,可能有偏(teacher 自己也 lose 一部分),但 PPO fine-tune 需要 value init
   - 不训:value head 留 random init,PPO fine-tune 前几百 iter 纯学 value
   - 建议训(风险#2 方案 2 "不管,让 value 学真 MC return")
3. **fine-tune 要不要加 KL penalty 到 BC policy?**
   - 加:防止 catastrophic forgetting,但要加超参
   - 不加:lr 低 + entropy_coef 低 足够约束
   - 建议不加,用 lr=1e-4 保守
