> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **EXECUTED(non-ideal outcome)**
> - 计划 BC warm-start AZ path:期望 ≥ 0.40 stricter
> - 实际 r010-012(`docs/4_runs/registry.md`):F1-D2 = 0.167(BC ckpt 0.75 → AZ self-play 摧毁 -0.58)
> - 数据点驱动 ADR-0009 closure(self-play RL plateau 不可救)
> - postmortem 见 `docs/5_history/r010_az_bc_warmstart_postmortem.md`

---

---
status: in_progress (Phase 1-3 done, Phase 4-6 待跑 in containers)
last_updated: 2026-04-27
proposed_runs: r009 (BC warm-start AZ on Stage 3 1-card)
---

# AZ 路线 sub-roadmap — Stage 3 closure 后 BC warm-start

> Stage 0/1/2/3 AZ pure self-play 已闭环 (memory `project_az_stage0_3_baselines`):
> vs F1-D2 plateau ≈ 0.10-0.15 跨 stage 不变,Stage 3 1-card masked 0.104 比
> PPO BC→PPO (0.214) 还弱。**self-play collapse 是结构性问题,需 BC warm-start
> 突破** (paradigm pivot 文档 P0-1,PPO 路线证 +0.24 dominant lever)。

## 元任务

突破 PPO ceiling 0.34 stricter (vs F1-D2 ≥ 0.40),验证 BC warm-start AZ 是
比 PPO BC→PPO 强还是同水平,据此判 curriculum 是否能推到 Stage 4。

## 已废 α/β/γ 路径

| 选项 | 状态 |
|---|---|
| α: AZ pure self-play Stage 0/1/2/3 baseline | **完成** (s055-s066),vs F1-D2 plateau,FAIL stricter |
| β: AZ + 卡 直接 Stage 3 | 已包含在 α (s064-s066) |
| γ: PPO 1-card 重测 | 已在 PPO closure 数据中 (s028-s030 0.214) |

## 当前路径: BC warm-start AZ

### Phase 0 — audit ActorCritic obs ✅ (2026-04-27)

ActorCritic 12-input forward,要求:
- per-game static (counter_sids, active_slot_mask, hook_types/values, char_skill_refs)
- per-step dynamic (counter_values, meta, card_buckets, enemy_sizes)
- per-step action (refs, payments)
- derived (structural_values, hook_emb)

PPO BC dataset 只存 flat dynamic + chosen action,不够 AZ 用,需新 dataset gen。

### Phase 1 — `tools/gen_bc_dataset_az.py` ✅ (2026-04-27)

F1-D2 vs F1-D2 mix F1-D1 self-play in Stage 3 1-card spec。每步存:
- per-game static_obs (raw bytes,训练时再 parse)
- per-step (game_id, dyn_obs, action_refs/payments, legal_mask, tied_mask, chosen_action, terminal_z)

测试: 已在 `configs/r009_bc_data_gen_stage3.toml` 运行成功,50,005 decisions
来自 4,629 games,teacher_self_wr=0.71,raw_legal mean=33 / p99=96。

### Phase 2 — `training/az/bc_train.py` ✅ (2026-04-27)

复用 ActorCritic forward。Loss = soft-target CE on tied_mask + value MSE on
terminal_z。Hyper: lr=1e-4, batch=256, epoch=60, value_coef=0.5
(mirror PPO s016d which broke F1-D2 hard-match ceiling)。

⚠️ **Host 内存超限事件 (2026-04-27)**: 在 host 上跑 bc_train 时,decompress
4 GB 静态 obs 导致 host 卡死。修复: bc_train 解析后立即 del + gc;**所有
后续训练改容器化** (Docker Desktop VM cap 9 CPU / 18 GB,OOM 限于容器内,
不影响 host)。详见 CLAUDE.md "Container workflow" 段。

### Phase 3 — `init_from_ckpt` 接口 ✅ (2026-04-27)

`AZConfig.init_from_ckpt: Optional[str]` + `train_loop/async_loop.py`
启动时 `challenger.net.load_state_dict(torch.load(...))`。

### Phase 4 — BC quality gate (待跑 in container)

BC ckpt 直接 evaluator (无 MCTS) 跑 7-baseline ladder
(random + mcts_50/100/200 + F1-D{1,2,3})。

**Gate**:
- vs F1-D2 ≥ 0.50 → BC 突破 PPO s016d 73% soft_match 类似水平 → 进 Phase 5
- vs F1-D2 0.30-0.50 → BC 部分 work,加 capacity (d_model=256) 重 train
- vs F1-D2 < 0.30 → BC pipeline bug,排查

注: 直接 evaluator 是 argmax over policy logits,无搜索。比真训练后跑会弱
一些 (search 加成)。

### Phase 5 — r009 production launch (待跑 in container)

`configs/r009_az_bc_stage3.toml` (待写):
- Stage 3 1-card masked spec (与 PPO 1-card masked s028-30 对照)
- `init_from_ckpt = "artifacts/<ts>_r009_bc_pretrain_stage3/final.pt"`
- multi-seed n=3 (r009/r010/r011 production 编号正式启用)
- 200-400 g per seed,arena + gauntlet 标配 (mcts_pure + F1-D{1,2,3})

### Phase 6 — verdict + commit

| AZ + BC vs F1-D2 | 解读 | 下一步 |
|---|---|---|
| ≥ 0.40 | **突破 PPO ceiling**,BC 是 dominant lever 在 AZ 也有效 | curriculum 推 Stage 4 + AZ + BC |
| 0.20-0.40 | BC 移植成功但仍需 P0-2 dense reward | 写 r010 加 dense HP delta |
| < 0.20 | BC 在 AZ 上 ROI 远低于 PPO | 排查 (lr / value_coef / hook_encoder grad flow) |
| < 0.10 | AZ + BC 比 PPO + BC 还弱 | 根本架构问题,paradigm 反思 |

## 关键决策 (已 align)

1. BC scenario: **Stage 3 1-card** (s028 同 spec) ← 与 PPO 直接对照
2. 数据规模: **50,005 decisions** (PPO s015 一致)
3. value target: **terminal z** (±1)
4. soft target T=**1.0**
5. AZ 不引入 P0-3 rollout (保持 strict AZ)

## 容器化部署 (2026-04-27 起)

所有 BC dataset gen / BC train / launch_config 必须在容器内跑:

```bash
tools/dc.sh build eval                                      # 一次
tools/dc.sh up -d eval                                      # eval 长 daemon
tools/dc.sh run --rm train python -m tools.gen_bc_dataset_az configs/r009_bc_data_gen_stage3.toml
tools/dc.sh run --rm train python -m training.az.bc_train configs/r009_bc_pretrain_stage3.toml
tools/dc.sh run --rm train python -m tools.launch_config configs/r009_az_bc_stage3_seed42.toml
```

详见 CLAUDE.md "Container workflow" 段。

## 风险

- **Risk A** (已发生): host 跑训练 OOM 卡机 → 容器化解决
- **Risk B**: BC ckpt → AZ training,arena 早期 ckpt 替换可能洗掉 BC signal。
  策略: 早期 (前 50 局) dirichlet noise 关 / 减小,让 BC policy 主导 self-play
- **Risk C**: BC dataset 50k 对 ActorCritic 2.6M 参数容量比偏小,可能 underfit
  vs F1-D2。 监控 train_policy_loss,若 epoch 60 末仍 > 1.5 加 capacity

## 参考

- ADR: [adr-0008 paradigm pivot](../../2_decisions/adr-0008-rl_paradigm_pivot.md), [adr-0007 ppo_bc_warmstart](../../2_decisions/adr-0007-ppo_bc_warmstart.md)
- 数据闭环: memory `project_az_stage0_3_baselines`
- PPO BC dominant lever 证据: [`../../5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)
- 容器化决策: CLAUDE.md "Container workflow"
