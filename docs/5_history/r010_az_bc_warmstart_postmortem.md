# r010 AZ + BC warm-start Stage 3 multi-seed postmortem

**Date**: 2026-04-28
**Status**: stricter FAIL (vs F1-D2 = 0.167 ± 0.029,远低 0.40 阈值)
**Total wall**: ~50min(3 seed × ~17min host-native,n_workers=4)

## Hypothesis under test

paradigm-pivot 文档(`memory project_rl_paradigm_pivot`)预测 PPO 路线 BC warm-start +0.24 dominant lever 在 AZ 路线同样有效,可突破 PPO Stage 3 ceiling 0.34 进入 stricter PASS (≥0.40)。

## Setup

- AZ Stage 3 1-card masked(同 s064-066 spec)
- `init_from_ckpt = r009 BC epoch_3.pt`(pairwise 选 ep=3 最佳)
- BC ckpt 自身 vs F1-D2 = **0.75**(Phase 4 验证)
- 3 seeds: 42/43/44(同 s064-066 convention)
- n_games=200, n_workers=4, host-native

## Results

| baseline | r010_seed42 (s42) | r010_seed43 (s43) | r010_seed44 (s44) | mean ± std |
|---|---|---|---|---|
| random | 0.875 | 1.000 | 0.875 | 0.917 ± 0.058 |
| mcts_pure_50 | 1.000 | 0.9375 | 1.000 | 0.979 ± 0.029 |
| mcts_pure_100 | 0.8125 | 0.75 | 0.625 | 0.729 ± 0.077 |
| mcts_pure_200 | 0.5625 | 0.5625 | 0.4375 | 0.521 ± 0.059 |
| F1-D1 | 0.625 | 0.5625 | 0.5625 | 0.583 ± 0.029 |
| **F1-D2** | 0.1875 | 0.125 | 0.1875 | **0.167 ± 0.029** |
| F1-D3 | 0.125 | 0.1875 | 0.125 | 0.146 ± 0.029 |

**Dual judge**:
- vs random ≥ 0.65 → curriculum PASS ✅(0.917)
- vs F1-D2 ≥ 0.40 → **stricter FAIL** ❌(0.167)

## 三栈对照(Stage 3 1-card stricter)

| 路线 | F1-D2 mean ± std | stricter PASS? |
|---|---|---|
| PPO Stage 3 best (BC→PPO 1card fullobs) | 0.344 ± 0.062 | ❌ |
| AZ pure self-play (s064-066) | 0.104 ± 0.072 | ❌ |
| **AZ + BC warm-start (r010)** | **0.167 ± 0.029** | **❌** |

**Stage 3 1-card stricter PASS (≥0.40) 三栈均失败,物理不可达**。

## 失败诊断

### BC 策略在 AZ self-play 中被摧毁

- BC ckpt(epoch_3)vs F1-D2 = **0.75**(Phase 4 验证,n=16)
- r010_seed42(BC + 200g AZ self-play)vs F1-D2 = **0.1875**
- **跌幅 -0.56**,超过任何 16-game 噪声(std=0.029-0.077 → 95% CI ~±0.06)

### Root cause: Distribution shift + MCTS exploration disrupts sharp BC policy

- BC argmax 是 sharp policy(选一个最优 tied 动作)
- AZ MCTS 把搜索预算分散到 BC 没考虑的动作 → 自对弈样本里有 BC 不会做的"探索动作"
- value head 学到这些"探索结果",反过来推 policy 远离 BC 的 hard-earned 偏好
- **200g 内 BC 优势被冲洗殆尽**

### 与 PPO 路线对比

PPO BC warm-start +0.24 因为:
- PPO 用固定 opponent (F1-D1/F1-D2 mix),分布稳定
- PPO importance sampling 保留 BC policy 偏好
- PPO 不做 search-distorted policy update

AZ self-play 失去这两个优势。

## 下一步候选

### 短期(1-3h 内可验)

1. **r016: KL retention loss** — `policy_loss = vanilla + λ·KL(π || π_BC)` 防漂移。
   - 风险: λ 调过紧,policy 不学;调过松,等价当前 r010
   - 验证成本: 200g × 3 seed ~50min
2. **r017: 短 AZ + 早 ckpt** — n_games=50,frequent gauntlet,看是否保留 BC 强度。
   - 验证成本: 50g × 3 seed × ~5min = ~15min

### 中期(>6h)

3. **mixed opponent training** — AZ self-play + 50% F1-D2 cross-play,稳定分布。
4. **distillation**: 用 BC 作 teacher,AZ value head 蒸馏 BC value;policy 也加蒸馏 KL。

### 战略选项

5. **接受 PPO 0.344 为 production**:Stage 3 stricter 物理不可达,降级阈值至 0.30(≈ PPO best)。
6. **回退 Stage 2**:Stage 3 1-card 不做 RL milestone;curriculum 闭环至 Stage 2(已验 PASS)。

## 工程教训

1. **wrapper bug**: `tools.multi_seed_launch._read_gauntlet` 在 train 进程退出后立即读 gauntlet_results.jsonl,但 eval_service 异步 dispatch,部分 baseline 还没写。需加 wait/poll until 7 lines。
2. **NNN drift (now fixed)**: 原 register_run 自增 NNN 不校验 label,加上 multi_seed_launch 自构造 label 用 next_nnn,killed launches 各占用 NNN slot,导致 r009-r012 多次 drift。修复后 register_run 校验 label NNN,multi_seed_launch 用显式 `seed_labels`,同 NNN 不同 seed 后缀(子行机制)。
3. **container PyTorch perf**: arm64 Linux container PyTorch 慢 host 12×(可能 missing Apple Accelerate / native BLAS optimizations),长跑 ML training 应 host-native。
4. **n_workers default issue**: AZ `fixed_1v1` preset 不设 n_workers,默认 1,导致 single-process selfplay+train 串行。生产 TOML 必须显式设 n_workers ≥ 2。

## Artifacts

- `artifacts/202604280713_r010_az_bcwarmstart_stage3_seed42/`
- `artifacts/202604280729_r010_az_bcwarmstart_stage3_seed43/`
- `artifacts/202604280746_r010_az_bcwarmstart_stage3_seed44/`
- BC ckpt: `artifacts/202604270918_r009_bc_pretrain_stage3/epoch_3.pt`

## 决策点

需要用户决策:
- (a) 立即跑 r016/r017 探索补救?
- (b) 接受三栈失败,迁回 PPO 0.344 production + 降低 stricter 阈值?
- (c) 转 Stage 2 curriculum 闭环,放弃 Stage 3?
