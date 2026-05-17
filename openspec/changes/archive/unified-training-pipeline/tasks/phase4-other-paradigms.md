---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../tasks.md
---

# Phase 4 — AZ + BC + PPO + CFR 接入 EpisodePolicy

> P3 验证 DMC 通过新管线后,本 phase 把剩余 4 paradigm 适配 6 protocol。
> 每 paradigm 单独 smoke 验证 ± tolerance,通过后 ship。

## 1. 总 LOC 估 / Wall

- **LOC 估**:~3000(4 paradigm × ~700 LOC adapter + 各自 test)
- **Wall 估**:~2 weeks(4 paradigm 串行,每 paradigm ~3 days)
- **Smoke 门槛**:每 paradigm 各自历史 baseline ± tolerance(详 §6)

## 2. P4-T1 AZ paradigm adapter

- [x] **P4-T1.1**:`training/paradigms/az/paradigm.py` AZParadigm 实现 6
  protocol 接入(~350 LOC)
- [x] **P4-T1.2**:`training/paradigms/az/config.py` AZParadigmConfig(MCTS
  c_puct / sims / temperature)(~100 LOC)
- [x] **P4-T1.3**:`training/paradigms/az/collector.py` AZ SelfPlayCollector
  (~300 LOC,wrap core actor + MCTS-driven episode)
- [x] **P4-T1.4**:`training/paradigms/az/loss.py` AlphaZeroLoss(KL policy
  + MSE value)(~150 LOC)
- [x] **P4-T1.5**:`training/paradigms/az/policy.py` MCTSPolicy(IS-MCTS +
  leaf eval via provider)(~400 LOC,from az/mcts.py)
- [x] **P4-T1.6**:`training/paradigms/az/network.py` head 组装(policy +
  value)(~100 LOC)
- [x] **P4-T1.7**:pytest cover AZ paradigm 集成(~250 LOC tests)

依赖:P3 ship

### Smoke 门槛 P4-T1

- F1-D2 win rate ≥ 历史 c1v7 r010 baseline - 0.03
- argmax vs mcts_200 ≥ 0.42(historical 0.45)
- value pred 与 episode reward divergence < 0.15

## 3. P4-T2 BC paradigm 抽出 + first-class

- [x] **P4-T2.1**:`training/paradigms/bc/paradigm.py` BCParadigm(~200 LOC)
- [x] **P4-T2.2**:`training/paradigms/bc/config.py` BCParadigmConfig(dataset
  path / target_mode / lr)(~80 LOC)
- [x] **P4-T2.3**:`training/paradigms/bc/collector.py` DatasetCollector(一
  次性 push,no env)(~150 LOC)
- [x] **P4-T2.4**:`training/paradigms/bc/buffer.py` DatasetBuffer(全量或
  memmap)(~150 LOC)
- [x] **P4-T2.5**:`training/paradigms/bc/loss.py` BCLoss(CE 或 KL soft)
  (~120 LOC)
- [x] **P4-T2.6**:`training/paradigms/bc/policy.py` BCPolicy(~80 LOC)
- [x] **P4-T2.7**:`training/paradigms/bc/network.py` head 组装(policy
  only)(~80 LOC)
- [x] **P4-T2.8**:r009 ckpt smoke 加载 + valid acc 重现(必 ± 0.005)
- [x] **P4-T2.9**:`training/az/bc_*.py` + `training/ppo/bc_*.py` 删除(LOC
  减 ~600)
- [x] **P4-T2.10**:`tools/gen_bc_dataset_az.py` → `tools/dataset/gen_bc_dataset.py`
  适配 paradigm-agnostic(~50 LOC modified)
- [x] **P4-T2.11**:pytest cover BC paradigm 集成 + r009 acc(~200 LOC tests)

依赖:P3 ship

### Smoke 门槛 P4-T2

- r009 ckpt valid acc = baseline ± 0.005
- soft target KL 收敛 trajectory 与 historical s017 smoke 重现

## 4. P4-T3 PPO paradigm 迁移

- [x] **P4-T3.1**:`training/paradigms/ppo/paradigm.py` PPOParadigm(~300 LOC)
- [x] **P4-T3.2**:`training/paradigms/ppo/config.py` PPOParadigmConfig(GAE
  λ / clip_ratio / vf_coef / ent_coef)(~100 LOC)
- [x] **P4-T3.3**:`training/paradigms/ppo/collector.py` RolloutCollector
  (vec env)(~250 LOC,from ppo/rollout.py)
- [x] **P4-T3.4**:`training/paradigms/ppo/buffer.py` RolloutBuffer(每 iter
  clear)(~150 LOC)
- [x] **P4-T3.5**:`training/paradigms/ppo/loss.py` PPOLoss(clipped surrogate
  + value MSE + entropy)(~200 LOC)
- [x] **P4-T3.6**:`training/paradigms/ppo/policy.py` PPOPolicy(sample from
  logits)(~100 LOC)
- [x] **P4-T3.7**:`training/paradigms/ppo/network.py` head 组装(policy +
  value)(~80 LOC)
- [x] **P4-T3.8**:`configs/ppo/archive_repro.toml` 写 2026-04 r004 等价 cfg
- [x] **P4-T3.9**:PPO smoke 重现 2026-04 r004 100 step metrics(± 5%)
- [x] **P4-T3.10**:pytest cover PPO paradigm(~200 LOC tests)

依赖:P3 ship

### Smoke 门槛 P4-T3

- 2026-04 r004 100 step 重现:`loss`, `entropy`, `kl_pred`, `clip_frac`
  四指标各 ± 5%
- F1-D2 win rate ≥ 0.36(historical r004 mean - 0.05 std)

## 5. P4-T4 CFR paradigm 适配

- [x] **P4-T4.1**:`training/paradigms/cfr/paradigm.py` CFRParadigm(~250 LOC)
- [x] **P4-T4.2**:`training/paradigms/cfr/config.py` CFRParadigmConfig(traversal
  budget / advantage_lr / strategy_lr)(~100 LOC)
- [x] **P4-T4.3**:`training/paradigms/cfr/collector.py` TraversalCollector
  (parallel by thread)(~300 LOC,from cfr/traversal.py)
- [x] **P4-T4.4**:`training/paradigms/cfr/buffer.py` ReservoirBuffer(~150 LOC)
- [x] **P4-T4.5**:`training/paradigms/cfr/loss.py` CFRLoss(advantage MSE +
  strategy MSE)(~200 LOC)
- [x] **P4-T4.6**:`training/paradigms/cfr/policy.py` AveragePolicyAct(~120 LOC)
- [x] **P4-T4.7**:`training/paradigms/cfr/network.py` head 组装(avg_policy
  + advantage)(~120 LOC)
- [x] **P4-T4.8**:`configs/cfr/archive_repro.toml`(reproduce r008 final
  iter)
- [x] **P4-T4.9**:CFR smoke 100 iter convergence(已知 r008 oscillation,
  smoke 仅验证管线通)
- [x] **P4-T4.10**:pytest cover CFR paradigm(~200 LOC tests)

依赖:P3 ship

### Smoke 门槛 P4-T4

- 100 iter 完成 + advantage loss 收敛
- Final iter random win rate ≥ 0.40(historical r008 iter 199 baseline)
- 不要求 F1-D2 win rate(CFR closure 已知)

## 6. P4-T5 全 paradigm 集成测试

- [x] **P4-T5.1**:跑全 5 paradigm 各自 smoke(serial mode `tools/run.py
  --dry-run` + 短 wall)
- [x] **P4-T5.2**:对比每 paradigm 历史 baseline ± tolerance(详 §2-5)
- [x] **P4-T5.3**:全 pytest pass + ruff + gofmt + check_line_limits
- [x] **P4-T5.4**:`docs/paradigms/<name>/notes.md` 加 P4 smoke 记录

## 7. P4 ship 门槛

P4-T1-T5 全 done + 5 paradigm smoke 通过 → P4 ship。
进入 P5(物理 mv + tools 重组)。

## 8. Cross-references

- 主 design → [`../design.md`](../design.md)
- Paradigm spec delta → `../specs/paradigm-{az,bc,ppo,cfr}/spec.md`
- Migration plan(D1 BC / D2 PPO)→ [`../design/migrations.md`](../design/migrations.md)
- Risks(R-F BC ckpt / R-G PPO repro)→ [`../design/risks.md`](../design/risks.md) §6, §7
- 历史 baseline:`docs/paradigms/{az,dmc,cfr,ppo,bc}/runs/` + `docs/4_runs/registry.md`
