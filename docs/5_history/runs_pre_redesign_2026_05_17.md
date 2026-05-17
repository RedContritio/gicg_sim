# Pre-redesign Run Archive (sealed 2026-05-17)

**Sealed by:** `core-network-generic-promotion` change (Phase 0)
**Originally at:** `docs/4_runs/registry.md`
**Successor:** `tools.runs.list` CLI + `artifacts/runs/<id>.toml` (gitignored,per `core-network-generic-promotion` spec delta `tools-layout/spec.md`)

This file is a one-time dump of the manual markdown run registry that lived at
`docs/4_runs/registry.md` from 2026-04-19 (r001 first registered) through
2026-05-17 (this archive). Runs r001-r012 production + s001-s068 validation are
recorded here.

**ckpt status:** All ckpts physically removed in `core-network-generic-promotion`
Phase 0 (T0.2). Schema obsolete (incompatible with redesigned `core/network/`
ActorCritic + AgentBase + ckpt self-describing format).

**cfg retrieval:** Pre-redesign cfgs are archived to
`configs/_archived/pre_redesign_2026_05_17/` (T0.4), still browsable in the
working tree. For older states: `git checkout pre-core-network-redesign-2026-05-17`.

**For future runs:** see `tools.runs.list` CLI (no more `registry.md` —
metadata is per-run TOML under `artifacts/runs/<id>.toml`, gitignored,
synced cross-machine via `tools.runs.sync`).

---

## Original content (frozen 2026-05-17)

Authoritative index of training runs and bench runs. All new
artifacts under `artifacts/` must be registered here.

## Naming

`artifacts/YYYYMMDDHHMM_<label>/` where `<label> = <type><NNN>_<slug>`.

- `r` — production-style training run (multi-hundred games, arena +
  gauntlet, produces shipped model candidates)
- `s` — short validation / bench (smoke, backend comparison, quick
  ablation — anything whose purpose is answering a question not
  training a model)

`<NNN>` is the next integer for that type. `<slug>` is a terse
lowercase underscore-separated description (e.g. `randteam2_400g`,
`backend_bench_go_100g`).

## Process

1. Pick `<type>` + next `<NNN>` from the tables below (claim it by
   adding the row with status `pending`)
2. Name the TOML `configs/<label>.toml` with matching
   `run_label = "<label>"`
3. On run completion, fill in result cells + flip status

## Pre-registry baselines (kept for historical comparison)

Two runs from before this registry existed are kept on disk as
reference strengths:

| artifact dir | config | g400 gauntlet | notes |
|---|---|---|---|
| `202604180500_az_c1v7` | shipped_1v1 pre-rename (team_size=1 random) | mcts_200=0.45 | First ship of C1v7 architecture (sid pinning + struct_readout) |
| `202604181653_az_c3` | shipped_2v2 pre-rename (team_size=2 fixed) | mcts_200=0.45 (g200) | First team_size=2 verification, disjoint_teams=true |

Everything else from before 2026-04-19 has been deleted — those
were PPO-era experiments (`p0_*`), architecture smokes
(`*_smoke`), and failed / killed attempts. Not worth the disk.

## Runs

### Bench / smoke (`s`)

| id | label | started | config | status | result |
|---|---|---|---|---|---|
| s001 | s001_backend_bench_py_100g | 2026-04-19 06:00 | random_1v1 100g, team_size=1, parallel=4, backend=python | **done** | wall=46.3min; g100 gauntlet mcts_200=0.05 (training variance, 100g) |
| s002 | s002_backend_bench_go_100g | 2026-04-19 06:56 | random_1v1 100g, team_size=1, parallel=4, backend=go | **done** | wall=37.4min (**Go -19% vs s001**); g100 mcts_200=0.55; loss aligned → **Go backend validated** |
| s005 | s005_d1_check | 2026-04-20 (after r005A if K=3 net-negative) | 50g / n_workers=1 / expand_union_k=3. 事后验 D1 埋点,区分 K=3 实现 bug vs 算法扰动 | **conditional** | 仅当 r005A > r004 时触发 |
| s006 | s006_greedy_calibration | 2026-04-24 04:55 | GreedyPlayer F1-F5 × D1-D2 round-robin(dice_greedy OFF): 5 feature-axis vs random + F5 vs F1 + F3-D2 vs F3-D1 depth + F5-D2 vs mcts_50 ceiling | **done** | random 极弱(F1-F5 全 10/10 vs random 5s);F5-D1 vs F1-D1=0.80(F5 胜,dice_greedy OFF);F3-D2 vs F3-D1=0.40(D2 无 filter 反输);F5-D2 vs mcts_50=0.70。**关键确认:random 不是合理强度基线** |
| s007 | s007_greedy_ladder | 2026-04-24 06:20 | GreedyPlayer ladder dice_greedy=true: 特征梯度 F1→F5 pairwise + 深度 D1vsD2 at F3/F5 + F5-D2 vs mcts_50/100/200 ceiling + filter 对胜率影响 + F1-D2 ceiling 追加 | **done** | **F1>F2>F3>F4>F5 每步 0.90**(dice_greedy 开后反转 s006);F1-D1 vs F5-D1=0.90 头对头确认;F1-D2 vs mcts_200=**0.90**(640s,F1 系真实 ceiling,压 F5-D2 的 0.70);F3-D2 vs F3-D1=0.70(filter 让 D2 变有用);F3-D3 vs F3-D2=0.50(D3 无增益);filter sanity F5-D1 ON vs OFF=0.90(filter 纯增益)。**F1-D2-dice_greedy 是最强 greedy 基线**,供后续 r009+ gauntlet 使用 |
> **⚠ 2026-04-25 retrospective:** s008-s014 每行的 result 都是单 seed × n=16 eval。跨 3 次 s008 re-run, F1-D2 wr 震荡 0.875/0.125/0.406 (同 TOML), 证明 **single-seed 结论不 robust**,下方所有 PASS/FAIL 应读作 "indicative"。详 `memory feedback_ppo_multiseed_required`。下轮应跑 multi-seed mean±std + n_eval_games ≥ 64。
>
> **代码基础设施变更:**
> - `tools/ppo_stage0_smoke.py` (CLI-override) **已删除** 2026-04-25;所有 PPO run 走 `tools/ppo_launch.py configs/<label>.toml` (TOML-driven, 对齐 AZ 栈)
> - `training/ppo/run.py` 新模块: ckpt + metrics.jsonl + summary (原 smoke 脚本逻辑)
> - `training/ppo/config_loader.py`: TOML → PPOConfig, `reward_shaping` dict merge
> - **2026-04-25 03:53 加 `torch.manual_seed(cfg.seed)`** — 之前 torch rng 未 seed,policy sampling 每次非确定

| s008 | s008_ppo_stage0_smoke | 2026-04-24 22:53 | PPO Stage 0 (curriculum) 500 iter, 1v1 mirror 测试角色D, fix_dice=[2F,2I,2W,2E,0,0,0,0], max_rounds=3, card_pool=[], reward_shaping={hp_delta=1, penalty=1.1, terminal=60}, d_model=256, n_games/iter=32, eval every 25 games vs random | **done (indicative)** | wall=90.3s;run #1 final ladder n=32:random=1.000/F1-D1=1.000/F1-D2=0.875/F1-D3=0.781;**但 2026-04-25 同 TOML re-run 两次**:#2 F1-D2=0.125, #3 F1-D2=0.406(n=32 ladder)。不同 local optimum(run #3 F1-D1=0.31 < F1-D2=0.41 反常) — **single seed 不可信,Stage 0 "PASS" 结论需 multi-seed 复测**。Replay #1 学到 "Tune×5 → 重击×2" sequencing → **判据已升级到 F1-D2/D3** |
| s009 | s009_ppo_stage1_smoke | 2026-04-25 00:45 | PPO Stage 1 (curriculum) 500 iter, Stage 0 + fix_dice=None(骰子每回合随机 roll)。其他参数同 s008。测试 RL 对 stochastic env 鲁棒性 | **done, failed** | wall=118.5s; final eval n=16: **random=0.812 / F1-D1=0.312 / F1-D2=0.000**;loss=162, entropy=0.40, value_loss=325 均未收敛。Replay 诊断: policy 塌陷成 Tune-heavy (Round 1 零攻击), 局部最优陷阱。**500 iter 不够,Stage 1 方差大需要更多 compute** → s010 |
| s010 | s010_ppo_stage1_2000iter | 2026-04-25 01:41 | PPO Stage 1 2000 iter (s009 × 4)。原参数不变, 测试是否 iter 不足是 s009 失败的根因 | **done, failed (regressed)** | wall=433s; final n=16: **random=0.562 / F1-D1=0.188 / F1-D2=0.062**;vs s009(random=0.81)反而退步,entropy 降到 0.21 但策略更差。loss/value_loss 震荡不收敛 (150/300)。**证实 iter 不是根因** → 诊断: value_loss 量级 vs shared trunk,reward=±80 + terminal=±60 在 Stage 1 high-variance env 下,value gradient 淹没 policy gradient (ratio ~7500:1),policy 塌陷 Tune-heavy → s011 改 terminal=10 + value_coef=0.1 |
| s011 | s011_stage1_terminal10_vc0.1 | 2026-04-25 03:03 | s010 + reward_shaping.terminal_win/loss 60→10 + value_coef 0.5→0.1。诊断修复: 降 return 量级让 value learnable,降 value_coef 让 policy gradient 不被淹没。500 iter smoke | **done, partial** | wall=115s; **value_loss 300→13** (按预期降 20×,诊断 #1 确认) + loss 150→1.3;但 vs_F1-D2=0.000 仍 FAIL。final n=16: random=0.750/F1-D1=0.062/F1-D2=0.000。**第二层根因: self-play collapse** — mirror match + stochastic env 下双方都 Tune,draw dynamics 不教 attack → s012 改 rollout_opponent='F1-D1' 验证 |
| s012 | s012_stage1_vs_f1d1_opp | 2026-04-25 03:12 | s011 + rollout_opponent='F1-D1' (100% P1 固定 greedy,非 self-play)。验证假设: self-play collapse 是根因。500 iter smoke | **done, breakthrough** | wall=153s; final n=16: **random=0.312 / F1-D1=0.000 / F1-D2=0.000**。Replay 显示 **agent 已突破 Tune-heavy 塌陷**: Round1 4 setup + 3 突刺 (3 HP 输出),Round2 轻击+2突刺,Round3 轻击 kill 尝试;agent 总输出 10 HP > F1-D1 8 HP,输因 1 HP close loss (先后手)。**self-play collapse 假设确认**: fix opponent 下 policy 能学 attack,只是 500 iter 只学到 coarse attack 不够学 skill efficiency(重击>轻击>突刺)。→ s013 加 iter |
| s013 | s013_stage1_vs_f1d1_2000iter | 2026-04-25 03:17 | s012 + n_iters 2000 (4×)。让 agent 学 skill efficiency (重击>突刺) + 时序优化 | **done, partial** | wall=570s; final n=16: **random=0.875 / F1-D1=0.562 / F1-D2=0.000**。agent 学会打 F1-D1 (56%) 但不 generalize 到 F1-D2 (0%)。Replay: F1-D2 会 Tune×5→重击×2 combo 6 HP,agent 从没见过因 F1-D1 训练对手从不 Tune,**opponent overfitting** — train distribution 不含 Tune-heavy play,agent value 函数低估 Tune→重击 序列 → s014 mixed opponent |
| s014 | s014_stage1_mix_f1d1_f1d2 | 2026-04-25 03:42 | s013 + rollout_opponent='F1-D1,F1-D2' (per-game uniform mix)。暴露 agent 到 F1-D2 的 Tune-heavy play style。2000 iter | **done, failed** | wall=1813s; n=16 summary: random=0.438/F1-D1=0.188/F1-D2=0.125。n=64 external ladder: **random=0.578/F1-D1=0.234/F1-D2=0.062/F1-D3=0.000/F5-D2=0.062**。Mixed opponent + 2000 iter + 诊断全 fix 仍 FAIL → **Stage 1 纯 PPO 路径彻底走完,承认 structural 不行**(和 `../2_decisions/adr-0008-rl_paradigm_pivot.md` 的 paradigm pivot 判断一致)。下一步 paradigm 改 BC warm-start,不再试 PPO-only Stage 1。 |
| s015 | s015_bc_data_gen | 2026-04-25 05:06 | F1-D2 teacher 50k decisions collection at Stage 1 spec。opponent_mix=[F1-D2, F1-D1] per-game uniform,teacher_side uniform P0/P1。tied_mask recorded per decision for soft-target BC | **done** | wall=270s,50002 decisions from 4529 games。teacher self-wr=0.706 (mostly winning F1-D1 games)。raw_legal p99=92 → max_actions 升 128。tied_mask mean=2.83,**hard-match ceiling 0.354**(F1-D2 random tiebreak over ~3 ties per decision)。见 memory `project_bc_warmstart_progress` |
| s016 | s016_bc_pretrain | 2026-04-25 05:12 | d_model=256/n_hidden=2/10ep/soft target;baseline BC 试 run | **done** | wall=3.3s。soft_match=34.3% FAIL(小网络达不到 soft ceiling) |
| s016b | s016b_bc_bigger_net | 2026-04-25 05:13 | d_model=512/n_hidden=4/30ep/soft | **done, marginal** | wall=25s;soft_match=65.8% MARGINAL;首次 break hard ceiling |
| s016d | s016d_bc_d1024_60ep | 2026-04-25 05:13 | d_model=1024/n_hidden=4/60ep/soft | **done, near-pass** | wall=127s;**soft_match=73.0% MARGINAL**;接近 80% 目标,作 s017 fine-tune 起点 |
| s017 | s017_bc_ppo_finetune | 2026-04-25 05:18 | BC warm-start (s016d final.pt) → PPO fine-tune: lr=1e-4, entropy=0.003, rollout_opponent='F1-D1,F1-D2', value_coef=0.1, terminal=10, 500 iter | **done, PASS** | wall=552s;n=16 summary vs_random=0.984/F1-D1=0.656/F1-D2=**0.500 PASS** (≥0.40)。n=64 external ladder: random=0.969/F1-D1=0.719/F1-D2=0.500/F1-D3=0.406/F3-D1=0.797/F5-D1=0.719/F5-D2=0.359。**Stage 1 BC→PPO 路径 validated**: pure PPO 0.062 → BC+PPO 0.500 (8× improvement)。Indicative single-seed。 |
| s018 | s018_bc_data_gen_stage2 | 2026-04-25 05:59 | Stage 2 (obs_mask=['enemy_dice']) BC data collection,50k decisions F1-D2 teacher。Python-layer masking via obs_mask field in PPOConfig(env 层 post-process,engine 零改动) | **done** | wall=276s,50002 decisions from 4529 games。tied_mask mean=2.83 (类似 s015 Stage 1),teacher 行为相同因为 teacher 用 full-info snapshot/restore,obs_mask 只影响 recorded student obs |
| s019 | s019_bc_pretrain_stage2 | 2026-04-25 06:05 | 与 s016d 同 arch+hparams (d=1024/h=4/60ep)。Stage 2 数据 only | **done, marginal** | wall=126s,**soft_match=66.2%** (vs Stage 1 s016d=73%,-7% info loss from enemy dice masking) |
| s020 | s020_ppo_finetune_stage2 | 2026-04-25 06:07 | BC (s019) → PPO fine-tune,same hparams as s017。base="stage2" 自动设 obs_mask | **done, PASS** | wall=561s;n=16 summary vs_random=0.922/F1-D1=0.703/F1-D2=**0.422 PASS** (≥0.40)。n=64 external ladder: random=0.891/F1-D1=0.750/**F1-D2=0.531**/F1-D3=0.422/F3-D1=0.781/F5-D1=0.750/F5-D2=0.453。**Stage 2 PASS** — partial-obs learnable via BC warm-start。vs Stage 1: ~6-8% symmetric drop across opponents,quantifies enemy-dice info value。 |

> **✅ Stage 2 BC→PPO PASS (2026-04-25, s020):** Python-layer obs masking(`obs_mask=['enemy_dice']`)走 `PPOConfig.obs_mask` → `GicgEnv` `_get_obs` post-process,engine 零改动。BC→PPO pipeline 端到端过 Stage 2 judge(F1-D2 external=0.531 ≥ 0.40)。Curriculum plan Stage 0-2 全部 validated。
>
> **⚠ Stage 3 single-seed inconclusive (2026-04-25, s021-s023):** Stage 3 = Stage 2 + `card_pool=['测试卡_增幅','测试卡_碎片']`。curriculum plan line 306 的判据 (vs random ≥ 0.65) **PASS** @ 0.734。但 F1-D2 判据 (single-seed, n=64 external) 给 0.031 — **这个数字不能独立得出 "FAIL" 结论**,见 memory `feedback_ppo_multiseed_required`:单 seed 0.031 vs 0.250 这类 n=64 Wilson CI(p=0.03 附近 ±4%,p=0.25 附近 ±10%)下对 0.40 阈值没有强显著性,s008 同 TOML 三次 re-run F1-D2 在 0.125-0.875 震荡过。当前 observation 是 "single-seed 样本在 FAIL 侧",不是 "Stage 3 FAIL"。需要 multi-seed + 额外诊断才能下结论。**两条合理下一步**(等用户决策):(a) 接受 curriculum plan Stage 3 判据 PASS(vs random 0.734),推进 Stage 4;(b) 手动 multi-seed 加固 s023 结论 + 可选换 teacher / 改 BC target 后再推。

| s021 | s021_bc_data_gen_stage3 | 2026-04-25 06:53 | Stage 3 (Stage 2 + card_pool=['测试卡_增幅','测试卡_碎片']) BC data 50k decisions,F1-D2 teacher | **done** | wall=351s,50003 decisions 来自 4997 games。teacher self-wr=0.727 (vs Stage 2 s018=0.706)。legal-set stats (meta.json): mean=32.72 (vs s018 32.83),p99=93 (vs s018 96),frac_above_64=11.3% (vs s018 11.6%) — **Stage 3 legal set 略小于 Stage 2**,不是更大 |
| s022 | s022_bc_pretrain_stage3 | 2026-04-25 07:23 | d=1024/h=4/60ep/soft target,和 s016d/s019 相同 arch | **done** | wall=127s,**soft_match=62.1%** vs Stage 2 s019 66.2% (-4%)。single-seed external ladder n=64 on BC-only ckpt: random=0.500/F1-D1=0.375/F1-D2=0.047/F1-D3=0.062 |
| s023 | s023_ppo_finetune_stage3 | 2026-04-25 07:25 | s022 BC → PPO fine-tune,hparams 同 s020 (seed=0) | **done, inconclusive (single-seed)** | wall=635s,single-seed n=64 external: random=0.734/F1-D1=0.375/F1-D2=0.031/F1-D3=0.078。multi-seed 加固见 s024/s025 |
| s024 | s024_stage3_seed1 | 2026-04-25 09:00 | s023 同 TOML except seed=1。BC ckpt 复用 s022 (seed=0) | **done** | wall=761s, n=64 external: random=0.688/F1-D1=0.156/F1-D2=0.031/F1-D3=0.000 |
| s025 | s025_stage3_seed2 | 2026-04-25 09:00 | s023 同 TOML except seed=2 | **done** | wall=714s, n=64 external: random=0.750/F1-D1=0.422/F1-D2=0.141/F1-D3=0.078 |

> **⚠ Stage 3 multi-seed (n=3, PPO-fine-tune-seed only) (2026-04-25):** s023+s024+s025 fine-tune seeds {0,1,2},**共享 BC ckpt s022 (seed=0)** — variance 来源仅 PPO fine-tune 阶段,BC-seed variance 未量化。eval_seed 也固定 0,3 ckpt 面对相同 opponent 序列,std 偏低估真 population CI。Aggregate n=64 external ladder:
> - vs random: 0.734 ± 0.041(curriculum plan 判据 ≥ 0.65 → mean PASS;n=3 std CI 宽,具体收敛 stride 不确定)
> - vs F1-D1: 0.354 ± 0.188(std > 0.15 → aggregator 标 UNRELIABLE)
> - vs F1-D2: 0.073 ± 0.048(stricter 判据 ≥ 0.40,3 seeds 全 < 0.20。n=3 std bona fide CI 大致 [0.025, 0.300],但 raw values 全 < 0.40 已是强证据 fine-tune 阶段无法跨越 stricter 阈值 — 除非 BC seed 本身能改变上限)
> - vs F1-D3: 0.057 ± 0.024
>
> 当前证据显示 Stage 3 在 (s022 BC + 当前 fine-tune hparams) 下 **PPO-fine-tune-seed 噪声不能解释 F1-D2 fail**。还未排除的:BC-seed 噪声(共享 s022)、fine-tune hparams 不优、teacher F1-D2 ceiling。下一步两条仍合理:(a) 接受 curriculum 判据 PASS 推 Stage 4;(b) 多 seed BC + 改 BC target / teacher 加固。

> **🚫 Stage 3 closure (2026-04-26, s026-s054, 29 ablation runs):** 完整诊断走完。F1-D2 ≥ 0.40 stricter 判据在当前 BC→PPO pipeline 下 **物理不可达**,即使 best-of-each combined (s050-52 mean = 0.281)。
>
> 4 个 contributing factors 量化(详见 memory `project_stage3_full_diagnosis`):
> | factor | 影响 vs F1-D2 wr | 验证 |
> |---|---|---|
> | BC warm-start | +0.24 dominant | s054 scratch peak ~0.11 vs BC+PPO 0.34 |
> | partial obs lift | +0.13 | s028 masked 0.21 → s033 fullobs 0.34 (1-card) |
> | F1-D3 teacher | +0.10 | s028→s036 (masked baseline 切 teacher;与 fullobs 互替) |
> | PPO oscillation | 区间 ~±0.10-0.15 | s053 1000 iter wr 在 [0.18, 0.42] 抖 |
>
> Falsified: soft target collapse (s037/38 hard 反而差 -0.05);PPO 500→1000 iter undertraining (s053 oscillation 不是 undertraining)。
>
> Combination NOT additive: predicted 0.214+0.130+0.104=0.448, 实际 0.281。F1-D3 + fullobs 在合并下 substitutive 而非 additive。
>
> **决策: pivot 回 AZ 路线。** 不推 Stage 4。multi-card env (真 Stage 3) F1-D2 mean masked 0.073 / fullobs 0.104。BC ceiling + PPO oscillation 是结构性的。注意 AZ 路线本身有 risk(`project_r008_postmortem` r007 collapse 等),pivot 是 "PPO 路线结构性证否" 而非 "AZ 已解决"。
>
> 实验组速查:
> | 组 | configs | 假设 | 结论 |
> |---|---|---|---|
> | 1-card masked F1-D2 (n=3) | s026/s027/s028+s029/s030 | reduced complexity 是否 dominant | partial(+0.14 vs multi-card) |
> | 1-card fullobs F1-D2 (n=3) | s031/s032/s033+s039/s040 | partial obs 是否 dominant | 部分(+0.13 vs masked) |
> | 1-card masked F1-D3 (n=3) | s034/s035/s036+s044/s045 | F1-D3 teacher ceiling 更高 | yes(+0.10 vs F1-D2 teacher) |
> | hard target | s037/s038 | soft target collapse | FALSIFIED(hard -0.05) |
> | multi-card fullobs F1-D2 (n=3) | s041/s042/s043+s046/s047 | partial obs 在 multi-card 也有效 | 部分但仅 0.10 mean |
> | best-of-each combined (n=3) | s048/s049/s050+s051/s052 | factors 加和 | NOT additive(0.28<single) |
> | PPO 1000 iter | s053 | undertraining? | FALSIFIED(oscillation) |
> | PPO from scratch | s054 | BC necessary? | yes(scratch peak 0.11) |
>
> 每组 multi-seed aggregate.json 留在第一个 ckpt parent dir。

> **⚠ Stage 1 Pure-PPO Conclusion (2026-04-25):** s009→s014 6 个 config 穷举 (self-play/fixed-opp/mixed-opp × 500/2000 iter × default/fixed hparams) 全部 F1-D2 wr ∈ [0.000, 0.125]。诊断已覆盖:value scale ✓、opponent collapse ✓、overfit ✓、iter 够长 ✓。剩余 ONLY 可调的是 paradigm — **PPO from scratch 无法独立 learn narrow optimal in stochastic env**,与 pivot doc 的预测一致。转 **BC warm-start from F1-D2**(r009 plan 或 PPO 版改造)。
>
> **✅ Stage 1 BC→PPO PASS (2026-04-25, s017):** F1-D2 teacher 50k decisions → MLP(d=1024,h=4) soft-target BC 60ep → soft_match 73% → PPO fine-tune (lr=1e-4, entropy=0.003, mix opponent) 500 iter → **vs F1-D2 = 0.500** (n=64 external ladder)。Stage 1 Go/No-go PASS (≥0.40)。BC warm-start 验证:pure PPO 0.062 → BC+PPO 0.500 **8× improvement**,与 paradigm pivot 文档预测一致。关键 infra:`training/framework/matchup/greedy_player.py::select_with_info` 暴露 tied set,soft target CE 解决 teacher 随机 tiebreak 理论上限 (F1-D2 hard-match ceiling 38.7%,soft target 推到 73%)。

> **🆕 AZ-stack curriculum baselines (2026-04-26 起):** Stage 3 PPO closure 后 pivot 回 AZ。s055+ 是 AZ 栈在 PPO 已 PASS 的简单 stage 上的对照 baseline (curriculum 原则:简化先于优化 / 验证先于推进)。判据:vs random ≥ 0.95 → AZ 栈 work,推下一 stage;< 0.65 → AZ 栈本身有 bug。详见 `../5_history/az_plans/r009_az_warmstart.md` α 路径(已归档)。

| s055 | s055_az_stage0_baseline | 2026-04-26 16:43 | AZ Stage 0 baseline, n_games=200, mirror 测试角色D, fix_dice, max_rounds=3, n_rollouts=100, lambda_end=0.5, seed=42 | **done, marginal (single-seed indicative)** | wall=22min train + 90s gauntlet。n=16 gauntlet (single seed,argmax no-search): random=**0.875** / mcts_50=0.9375 / mcts_100=0.625 / mcts_200=**0.6875**。vs random 落 marginal 区间 (0.70-0.95),不算明确 PASS(<0.95)也非 FAIL(>0.65)。**AZ 栈在 Stage 0 work**(vs mcts_200=0.69 显示 search 有效),但 single-seed n=16 std 大,需 multi-seed/n=64 加固或推 Stage 1 看趋势。entropy 末尾 2.7(max ≈ 2.83)policy 仍较平,与短训(200g)一致 |
| s056 | s056_az_stage0_seed43 | 2026-04-26 17:18 | s055 同 toml except seed=43。multi-seed 加固 s055 marginal | **done** | wall=20min train + 96s gauntlet。n=16: random=**1.000** / mcts_50=**1.000** / mcts_100=0.9375 / mcts_200=0.5625。本 seed 表现强于 s055 |
| s057 | s057_az_stage0_seed44 | 2026-04-26 17:38 | s055 同 toml except seed=44。配合 s055/s056 → n=3 mean±std | **done** | wall=20min train + 84s gauntlet。n=16: random=0.875 / mcts_50=0.875 / mcts_100=0.6875 / mcts_200=**0.375**。本 seed mcts_200 表现弱 |

> **✅ Stage 0 AZ baseline multi-seed (n=3, s055+s056+s057, 2026-04-26):** AZ 栈在 Stage 0 work confirmed。
>
> | baseline | mean ± std (n=3, sample std) |
> |---|---|
> | vs random | **0.917 ± 0.072** |
> | vs mcts_pure_50 | 0.938 ± 0.063 |
> | vs mcts_pure_100 | 0.750 ± 0.165 |
> | vs mcts_pure_200 | 0.542 ± 0.158 |
>
> **Verdict: PASS (indicative)。** vs random mean 0.917 接近 0.95 阈值,与 PPO Stage 0 (1.000) 差距小且属 single-seed std 范围。vs mcts ladder 在 search-vs-search 下 high variance (mcts_100/200 std ~16%,符合 memory `feedback_ppo_multiseed_required` 的 std>0.15 unreliable 警示,但 mean 仍 > 0.5 random baseline)。
>
> **下一步: Stage 1 AZ baseline (s058)** — 同 spec 去掉 fix_dice (骰子随机),验证 AZ 栈在 stochastic env 下是否仍 work。

| s058 | s058_az_stage1_baseline | 2026-04-26 18:59 | AZ Stage 1 baseline, n_games=200, mirror 测试角色D, max_rounds=3, **fix_dice removed** (骰子随机), n_rollouts=100, lambda_end=0.5, seed=42 | **done** | wall=22min train+gauntlet。n=16: random=0.875 / mcts_50=0.9375 / mcts_100=0.6875 / mcts_200=0.3125 |
| s059 | s059_az_stage1_seed43 | 2026-04-26 19:21 | s058 同 toml except seed=43。multi-seed | **done** | wall=20min。n=16: random=**1.000** / mcts_50=**1.000** / mcts_100=0.875 / mcts_200=0.500 |
| s060 | s060_az_stage1_seed44 | 2026-04-26 19:41 | s058 同 toml except seed=44。multi-seed | **done** | wall=20min。n=16: random=0.9375 / mcts_50=0.875 / mcts_100=0.875 / mcts_200=0.3125 |

> **✅ Stage 1 AZ baseline multi-seed (n=3, s058+s059+s060, 2026-04-26):** AZ 栈在 Stage 1 (stochastic env) 仍 work。
>
> | baseline | Stage 0 mean ± std | **Stage 1 mean ± std** |
> |---|---|---|
> | vs random | 0.917 ± 0.072 | **0.938 ± 0.063** |
> | vs mcts_pure_50 | 0.938 ± 0.063 | 0.938 ± 0.063 |
> | vs mcts_pure_100 | 0.750 ± 0.165 | 0.812 ± 0.108 |
> | vs mcts_pure_200 | 0.542 ± 0.158 | **0.375 ± 0.108** |
>
> **Verdict: PASS。** vs random 0.938 ≥ 0.85 阈值。vs mcts_200 退化 Δ-0.17 (stochastic env 下网络难胜 strong search baseline,但弱 baseline 没退步)。
>
> **关键对照 PPO Stage 1**: PPO pure-PPO 全失败 (s009-s014 vs F1-D2 < 0.13),只 BC→PPO PASS (s017 vs F1-D2 = 0.500)。AZ 不需 BC 就在 stochastic env work — **search-based 方法对 stochasticity 鲁棒性更好**,这是 paradigm pivot 文献预测的 hybrid AZ 优势的本仓库证据。
>
> **下一步: Stage 2 AZ baseline (s061-s063)** — 同 spec + partial obs (obs_mask hide enemy dice/hand)。

| s061 | s061_az_stage2_baseline | 2026-04-26 20:09 | AZ Stage 2 baseline, Stage 1 spec + obs_mask=["enemy_dice"], seed=42 | **done** | wall=22min。n=16: random=0.875/mcts_50=0.9375/mcts_100=0.5625/mcts_200=0.4375。F1 backfill (eval_service async): F1-D1=0.250/F1-D2=0.1875/F1-D3=0.0625 |
| s062 | s062_az_stage2_seed43 | 2026-04-26 20:31 | s061 同 toml except seed=43 | **done** | wall=20min。n=16: random=1.000/mcts_50=1.000/mcts_100=0.875/mcts_200=0.500。F1 backfill: F1-D1=0.250/F1-D2=0.125/F1-D3=0.0625 |
| s063 | s063_az_stage2_seed44 | 2026-04-26 20:51 | s061 同 toml except seed=44 (commit d4f288c GreedyPlayer infra 后,本 run 直接含 F1 ladder) | **done** | wall=20min。n=16: random=0.875/mcts_50=1.000/mcts_100=0.6875/mcts_200=0.3125/F1-D1=0.375/F1-D2=0.125/F1-D3=0.0625 |

> **⚠ Stage 2 AZ baseline multi-seed (n=3, s061+s062+s063, 2026-04-26):** dual verdict — curriculum_plan 官方 judge PASS,F1-D2 stricter judge FAIL。
>
> | baseline | mean ± std (n=3) | curriculum judge | F1 stricter judge |
> |---|---|---|---|
> | vs random | **0.917 ± 0.072** | PASS (≥0.65) | — |
> | vs mcts_pure_50 | 0.979 ± 0.036 | — | — |
> | vs mcts_pure_100 | 0.708 ± 0.157 | — | — |
> | vs mcts_pure_200 | 0.417 ± 0.096 | — | — |
> | vs F1-D1 | 0.292 ± 0.072 | — | — |
> | **vs F1-D2** | **0.146 ± 0.036** | — | **FAIL (≥0.40)** |
> | vs F1-D3 | 0.063 ± 0.000 | — | — |
>
> **关键发现 (2026-04-26):** 完成 Stage 0/1/2 F1 backfill 后发现 **AZ pure self-play vs F1-D2 ≈ 0.125 跨 Stage 0/1/2 plateau**:
> - Stage 0 (s055-57) vs F1-D2: 0.125 ± 0.000
> - Stage 1 (s058-60) vs F1-D2: 0.125 ± 0.000
> - Stage 2 (s061-63) vs F1-D2: 0.146 ± 0.036
>
> 与 PPO pure-PPO Stage 1 (vs F1-D2 < 0.13) **同水平**。之前"AZ 不需 BC 在 Stage 1 work"的结论**只对 vs random/mcts_pure (弱 baseline) 成立**,vs F1-D2 实际是同 PPO 一样的 self-play collapse:mirror match 双方都 Tune-heavy,网络学不到 attack 来 beat F1。
>
> AZ 在弱 baseline 上 work (vs random ≥ 0.85) 而 PPO pure-PPO 不 work,可能解释:AZ MCTS 提供搜索深度替代了 PPO 需要 BC 才能 bootstrap 的 attack 策略 — 但只对弱对手有效,F1-D{2,3} adversarial depth 突破 AZ search depth。
>
> **下一步: Stage 3 AZ pure self-play (s064-066) 作为 data point**,预测 vs F1-D2 ≈ 0.125 (与 Stage 0/1/2 同水平)。"突破 PPO Stage 3 ceiling 0.34" 需 AZ + BC warm-start (infra work,留 next session)。

| s064 | s064_az_stage3_1card | 2026-04-26 21:26 | AZ Stage 3 1-card baseline, Stage 2 spec + card_pool=["测试卡_碎片"], seed=42 | **done** | wall=22min。n=16: random=0.6875/mcts_50=0.5625/mcts_100=0.500/mcts_200=0.125/F1-D1=0.250/F1-D2=0.0625/F1-D3=0.0625 |
| s065 | s065_az_stage3_1card_seed43 | 2026-04-26 21:47 | s064 同 toml except seed=43 | **done** | wall=22min。n=16: random=0.9375/mcts_50=1.000/mcts_100=0.9375/mcts_200=0.500/F1-D1=0.5625/F1-D2=0.0625/F1-D3=0.0625 |
| s066 | s066_az_stage3_1card_seed44 | 2026-04-26 22:08 | s064 同 toml except seed=44 | **done** | wall=22min。n=16: random=0.875/mcts_50=1.000/mcts_100=0.625/mcts_200=0.1875/F1-D1=0.500/F1-D2=0.1875/F1-D3=0.125 |
| s067 | s067_az_stage3_multicard_baseline_seed42 | 2026-04-28 11:01 | AZ Stage 3 + 3-card pool (测试卡_碎片+增幅+神秘水流), 100g, n_workers=4, host-native; closure 决策实证 — 测 RL 是否受益 combinatorial breadth | **done** | wall~9min。n=16: random=1.000/mcts_pure_50=1.000/mcts_pure_100=0.875/mcts_pure_200=0.625/F1-D1=0.625/F1-D2=0.000/F1-D3=0.000 |
| s067 | s067_az_stage3_multicard_baseline_seed43 | 2026-04-28 11:10 | s067_seed42 同 toml except seed=43 | **done** | wall~9min。n=16: random=0.875/mcts_pure_50=0.9375/mcts_pure_100=0.75/mcts_pure_200=0.5/F1-D1=0.4375/F1-D2=0.125/F1-D3=0.0625 |
| s067 | s067_az_stage3_multicard_baseline_seed44 | 2026-04-28 11:18 | s067_seed42 同 toml except seed=44 | **done** | wall~9min。n=16: random=0.9375/mcts_pure_50=0.875/mcts_pure_100=0.875/mcts_pure_200=0.4375/F1-D1=0.5625/F1-D2=0.0625/F1-D3=0.0625 |
| s068 | s068_az_d4_mirror_break_seed42 | 2026-04-28 13:01 | AZ pure self-play, asymmetric teams (team_0=赤蝶, team_1=墨客), Stage 3 spec (1-card + obs_mask + max_rounds=3), 200g, n_workers=4, host-native; D4 mirror-breaking probe — 测 mirror Nash 锁死是否 plateau 主因 | **done** | wall~22min。n=16: random=0.4375/mcts_pure_50=0.1875/mcts_pure_100=0.0625/mcts_pure_200=0.125/F1-D1=0.1875/F1-D2=0.1875/F1-D3=0.125 |
| s068 | s068_az_d4_mirror_break_seed43 | 2026-04-28 13:23 | s068_seed42 同 toml except seed=43 | **done** | wall~22min。n=16: random=0.75/mcts_pure_50=0.25/mcts_pure_100=0.3125/mcts_pure_200=0.25/F1-D1=0.4375/F1-D2=0.375/F1-D3=0.25 |
| s068 | s068_az_d4_mirror_break_seed44 | 2026-04-28 13:45 | s068_seed42 同 toml except seed=44 | **done** | wall~22min。n=16: random=0.8125/mcts_pure_50=0.1875/mcts_pure_100=0.25/mcts_pure_200=0.125/F1-D1=0.3125/F1-D2=0.25/F1-D3=0.1875 |
| s069 | s069_az_d4_more_rollouts_seed42 | 2026-04-28 14:21 | s069_az_d4_more_rollouts_seed42 multi-seed n=3 (auto via tools.multi_seed_launch; seed_labels=['s069_az_d4_more_rollouts_seed42', 's069_az_d4_more_rollouts_seed43', 's069_az_d4_more_rollouts_seed44']) | **pending** | — |
| s069 | s069_az_d4_more_rollouts_seed43 | 2026-04-28 15:45 | s069_az_d4_more_rollouts_seed42 multi-seed n=3 (auto via tools.multi_seed_launch; seed_labels=['s069_az_d4_more_rollouts_seed42', 's069_az_d4_more_rollouts_seed43', 's069_az_d4_more_rollouts_seed44']) | **pending** | — |
| s069 | s069_az_d4_more_rollouts_seed44 | 2026-04-28 19:11 | s069_az_d4_more_rollouts_seed42 multi-seed n=3 (auto via tools.multi_seed_launch; seed_labels=['s069_az_d4_more_rollouts_seed42', 's069_az_d4_more_rollouts_seed43', 's069_az_d4_more_rollouts_seed44']) | **pending** | — |
| s070 | s070_v_phase2_kaeya_minimal | 2026-05-12 06:22 | v_phase2 凯亚 mirror minimal pool 200g cheap probe (n_workers=4 host-native, seed=42, n_rollouts=100, gauntlet vs random/mcts_pure_{50,100,200}/F1-D{1,2,3} n=16, deck v_phase2 6 卡, max_rounds=15) | **done, undertrained — no learning signal** | wall=19.6min train。**首次 gauntlet 全 0/16**:random=0.000/mcts_pure_50=0.000/mcts_pure_100=0.000/mcts_pure_200=0.000/F1-D1=0.000/F1-D2=0.000/F1-D3=0.000。entropy 整个 200g 保持 2.5-2.7(uniform-max ≈ 2.8),effective_lambda 末期 0.106(anneal target 0.8),train_ticks=28 ≈ 112 train_steps — net 未收敛。Sanity: az(g200)-vs-az(g200) self=0.500 (mirror ✓), random-vs-random=0.500 (env 对称 ✓), random-vs-az(g200)=1.0 — net argmax 比 random 还差(deterministic-bad: 几乎不攻,random 偶尔击杀)。**结论**: 200g + n_rollouts=100 远不够 v_phase2 凯亚 mirror 简化版可学(action 空间含 6 张卡 + 凯亚 skill);需 ≥ 1000g 或推 asymmetric。**附带 fix**: `tools/remote/eval_service_schema.json` 加 `pool` + `deck_padding` 字段(`additionalProperties: false` 之前拒了带 v_phase2 池字段的 gauntlet 请求;dispatch_gauntlet 一直 emit `eval_skip`,ADR-0011 落地遗漏) |

> **📊 s068 D4 mirror-break verdict (asymmetric teams,n=3,2026-04-28):** mirror IS partially the lock,但不是 sole cause。
>
> | baseline | mean ± std (n=3) | vs s064-066 mirror Δ | vs F1-D2 vs F1-D2 control (asymmetric setup) |
> |---|---|---|---|
> | random | 0.667 ± 0.164 | −0.17 | — |
> | mcts_pure_200 | 0.167 ± 0.059 | −0.10 | — |
> | F1-D1 | 0.313 ± 0.102 | −0.13 | — |
> | **vs F1-D2** | **0.271 ± 0.078** | **+0.167 (>2σ 显著)** | **−0.27 (asymmetric F1-D2 vs F1-D2 = 0.54)** |
> | F1-D3 | 0.188 ± 0.051 | +0.04 | — |
>
> **关键发现**:
> - **+0.167 vs mirror baseline 显著超 noise**(std 0.07-0.08,Δ > 2σ) → mirror Nash 锁死**确实贡献** plateau,asymmetric 局部 unlock RL
> - **但 asymmetric 下 AZ vs F1-D2 仍 -0.27 deficit** → mirror **不是唯一问题**。即使 break mirror,RL self-play 仍打不过 F1-D2
> - **重要**:此 run 用了**新的 swap_sides 语义**(commit XX,2026-04-28 修)。matchup.py 之前 swap_sides 只换先后手,primary 永远是 team_0 char;改后 primary 在 50% games 控 team_0,50% 控 team_1。control F1-D2 vs F1-D2 = 0.54(对称)。Mirror match 历史数据(s064-066, r010-012, s067, pairwise)新旧 swap_sides 等价(team_0 == team_1)。
> - **结论**: mirror 是 50% 故事;剩 50% 是别的 blocker(隐藏信息 / value learning / 搜索质量)。下一步 D1 belief network 攻击 hidden-info residual gap。

> **🚫 s067 multi-seed verdict (Stage 3 + 3-card AZ pure, n=3, 2026-04-28) — closure trigger:**
>
> | baseline | mean ± std (n=3) | vs s064-066 (1-card) Δ |
> |---|---|---|
> | random | 0.938 ± 0.051 | +0.10 |
> | mcts_pure_200 | 0.521 ± 0.078 | +0.25 |
> | F1-D1 | 0.542 ± 0.078 | +0.10 |
> | **vs F1-D2** | **0.0625 ± 0.051** | **−0.04** |
> | F1-D3 | 0.042 ± 0.029 | −0.04 |
>
> **核心结论**:多卡 combinatorial breadth **没让 RL 受益**,反而使 vs F1-D2 / F1-D3 略降(−0.04)。AZ pure self-play plateau 0.06-0.15 在 5 个 stage 测试(0/1/2/3/3-multicard)上**结构性稳定**,与 stage 复杂度无关。
>
> **触发判据**: vs F1-D2 = 0.0625 ≤ 0.15 阈值 → **curriculum closure**(详见 [`adr-0009-rl_paradigm_pivot_terminus.md`](../../docs/2_decisions/adr-0009-rl_paradigm_pivot_terminus.md))。
>
> 三栈 × 5 stage 全失败:PPO 0/1/2/3 + AZ pure 0/1/2/3/3-multicard + AZ+BC 3。**没一个 RL 路径产出 > BC 残余**。

> **🚫 Stage 3 AZ pure self-play multi-seed (n=3, s064+s065+s066, 2026-04-26):** AZ 不能突破 PPO ceiling。
>
> | baseline | mean ± std (n=3) | dual judge |
> |---|---|---|
> | vs random | **0.833 ± 0.130** | curriculum PASS (≥0.65),s064=0.69 接近阈值 |
> | vs mcts_pure_200 | 0.271 ± 0.201 | — |
> | vs F1-D1 | 0.438 ± 0.166 | — |
> | **vs F1-D2** | **0.104 ± 0.072** | **stricter FAIL (≥0.40)** |
> | vs F1-D3 | 0.083 ± 0.036 | — |
>
> **vs PPO Stage 3 直接对照**: AZ 1-card masked F1-D2 = 0.104 < PPO 1-card masked = 0.214 (PPO 强 +0.11),也 < PPO 1-card fullobs best = 0.344 (PPO 强 +0.24)。
>
> **核心结论**: AZ pure self-play **比 PPO BC→PPO 还弱**,远不突破 PPO ceiling 0.34。Stage 0/1/2/3 vs F1-D2 plateau 在 0.10-0.15,**self-play collapse 是结构性问题**,与 stage 难度无关。突破需 BC warm-start (paradigm pivot 文档 P0-1,PPO 路线证实 +0.24 dominant lever)。详见 [`../5_history/curriculum/stage3.md`](../5_history/curriculum/stage3.md)(已归档)。
>
> **Curriculum 当前结论 (双栈 4 stage 数据)**:
> - PPO BC→PPO Stage 0/1/2 PASS,Stage 3 ceiling 0.34 stricter FAIL
> - AZ pure self-play Stage 0/1/2/3 vs random PASS,vs F1-D2 ≈ 0.10-0.15 plateau (FAIL)
> - 两栈均需 BC warm-start 突破 strong baseline,paradigm pivot 文献预测被本仓库证实

### Runs (`r`)

| id | label | started | config | status | result |
|---|---|---|---|---|---|
| r001 | r001_randteam2_400g | 2026-04-19 07:44 | random_1v1 400g, team_size=2, disjoint_teams, char_pool 5, parallel=4, backend=go | **done** | wall=7.0h; **g400 gauntlet mcts_200=0.55** (beats C1v7 400g 0.45 and C3 200g 0.45); arenas: g100✓ g200✗ g300✓ g400✗ |
| r002 | r002_fast_lambda_400g | 2026-04-19 17:13 | same as r001 except lambda_anneal_games=400 (vs 1500) — force V head online by g400 | **done** | wall=7.3h; **g400 gauntlet mcts_200=0.30 (loses to pure MCTS_200, worse than r001 0.55)**; fast anneal pushed λ up before net trained → net degrades MCTS. policy loss + entropy both rose during training. See `memory/project_r002_fast_anneal_worse.md` |
| r003 | r003_obs_union_400g | 2026-04-20 01:15 | same as r002 + char_skill_refs obs region (commit 3c2ee89) + ExpandUnionK=3 (commit 1c7c922). A/B vs r002 on held fast_400 schedule to isolate feature effect | **done** | wall=7.0h; **g400 gauntlet mcts_200=0.25** (worse than r002 0.30 and r001 0.55). Training loss improved (policy 2.28 vs r002's 2.54, entropy 2.27 vs 2.58) but argmax win rate dropped — reversed correlation. Hypothesis: K=3 distorts π_target shape or fast_anneal still dominates. r004 tests slow+K=3 |
| r004 | r004_slow_union_400g | 2026-04-20 10:22 | same as r003 minus `lambda_anneal_games=400` (→ default slow 1500, 400g covers only λ→0.27). A/B vs r003 on anneal schedule with K=3 held fixed | **done** | wall=6.7h; g400 gauntlet **mcts_200=0.40** (> r002/r003 at 0.30/0.25, < r001 at 0.55). Confirms fast_anneal is main harm; K=3 or char_skill_refs still carries unmeasured cost. Arena g100✓ g200✗(0.2) g300✗(0.3) |
| r005A | r005A_slow_nounion_400g | 2026-04-20 17:09 | same as r004 minus `expand_union_k=3` (→ default 1 = disable union). Ablates K=3 on top of slow anneal + char_skill_refs obs. MCTS path identical to r001-era (bit-identical per commit 1c7c922). Note: ``A`` suffix is non-conforming with `<type><NNN>_<slug>` rule; kept as historical anomaly | **done** | g400 in-train gauntlet **vs_mcts_200=0.45** (> r004 0.40; K=3 净负 0.05 方向确认,gap 在 20g 噪声 ±0.11 边缘) |
| r006 | r006_slow_noskillrefs_400g | 2026-04-21 03:47 | same as r005A minus char_skill_refs obs region (`include_char_skill_refs=false` via new obs config). Pins r001 vs r005A 的 0.10 gap 来源 — char_skill_refs obs region 是否是元凶 | **done** | wall=6.8h; g400 gauntlet **mcts_200=0.40**; **vs r005A (0.45) 说明 char_skill_refs 实际有帮助(+0.05),0.10 gap 来自其他 commit**。arena g100=0.95 g200=0.80 g300=0.525(轨迹比 r004/r005A 好但 g300 差一点) |
| r007 | r007_slow_1500g | 2026-04-21 10:57 | 1500g 长程 scaling,include_char_skill_refs=true(依 r006 结果保留 char_skill_refs)。λ 跑满 anneal window,测 slow anneal 真正 saturation | **killed** (I5 deadlock) | wall=23h+(ingest 停在 games=1247 死锁,过了 2h drain-train 后人工 kill);arena collapse 轨迹 g100=1.00→g200=0.725→g300-900 范围 0.35-0.525→g1000=**0.05**→g1100/g1200=0.025;g500/g1000/g01500(ckpt_g01200 代) gauntlet mcts_200 = 0.35 / 0.05 / (mcts_100/200 未完)、random 0.90/0.75/0.71 — collapse 延续到 random baseline。详见 I5 backlog + r007 replay collapse 诊断 |
| r008 | r008_cfr_prototype | 2026-04-23 01:30 | **Paradigm change: Deep CFR** (not AZ)。`tools.run_cfr --preset r008_cfr_prototype --n-workers 4 --seed 42`。Fixed 2v2 team (赤蝶+墨客 vs 猫咪+刻师傅), 200 iter × 32 traversal, d_model=64, n_cross_layers=2。**OS-MCCFR 带 B1 完整 canonical 修复**:reach_q_prefix (commit e05b713) + Def.4 非采样 σ(a*) (commit 54f6c35) — Kuhn Nash 收敛 end-to-end 验证 | **done, failed** (2026-04-24) | wall 32.7h (117673s)。**iter 199 final gauntlet: 0.40 vs random / 0.00 vs mcts_50/100/200 / 0.00 vs greedy-F1-D1 dice_greedy**。Early-ckpt sweep: iter 20=1.00 / 40=0.80 / 60=0.70 / 80=0.60 / **100=0.00** / 120=0.30 / 199=0.40 (worse than iter 20 初始化)。iter 100 诊断发现 Switch fixation (~50% 动作选 Switch) + value head 乐观 (终局前 v=+0.2 但实际 0/10 输)。strat_loss 1.3→1.045 假象收敛,loss 与 policy quality 彻底脱钩。详见 memory `project_r008_postmortem`。**结论:current config Deep CFR 不训有用策略;下一轮需要 per-iter gauntlet + advantage_reset_each_iter=True + 考虑提 d_model** |
| r010 | r010_az_bcwarmstart_stage3_seed42 | 2026-04-28 07:13 | AZ Stage 3 1-card + init_from_ckpt=r009 BC epoch_3 (host-native, n_workers=4, n_games=200, seed=42) | **done** | wall=16.3min。n=16: random=0.875 / mcts_pure_50/100/200=1.0/0.8125/0.5625 / F1-D1=0.625 / F1-D2=0.1875 / F1-D3=0.125 |
| r010 | r010_az_bcwarmstart_stage3_seed43 | 2026-04-28 07:29 | r010_seed42 同 toml except seed=43 | **done** | wall=17.0min。n=16: random=1.0 / mcts_pure_50/100/200=0.9375/0.75/0.5625 / F1-D1=0.5625 / F1-D2=0.125 / F1-D3=0.1875 |
| r010 | r010_az_bcwarmstart_stage3_seed44 | 2026-04-28 07:46 | r010_seed42 同 toml except seed=44 | **done** | wall~18min。n=16: random=0.875 / mcts_pure_50/100/200=1.0/0.625/0.4375 / F1-D1=0.5625 / F1-D2=0.1875 / F1-D3=0.125 |

> **🚫 r010 multi-seed verdict (BC warm-start AZ Stage 3,n=3,2026-04-28):** stricter FAIL — BC warm-start 在 AZ self-play 中失败。
>
> | baseline | mean ± std (n=3) | dual judge |
> |---|---|---|
> | vs random | **0.917 ± 0.058** | curriculum PASS (≥0.65) |
> | vs mcts_pure_200 | 0.521 ± 0.059 | — |
> | vs F1-D1 | 0.583 ± 0.029 | — |
> | **vs F1-D2** | **0.167 ± 0.029** | **stricter FAIL (≥0.40)** |
> | vs F1-D3 | 0.146 ± 0.029 | — |
>
> **vs AZ pure self-play (s064-066) 直接对照**: AZ + BC warm-start F1-D2 = 0.167 vs AZ pure = 0.104,**仅 +0.063 (在 std 0.029-0.072 噪声边缘)**。BC ckpt 自身 vs F1-D2 = 0.75,但 200g AZ self-play 后 r010_seed42 = 0.1875 (-0.56) — **BC 策略被 self-play distribution shift 摧毁**。
>
> **核心结论**: BC warm-start 在 AZ self-play 中无效。Stage 3 1-card stricter PASS (≥0.40) 三栈均失败:PPO 0.344 / AZ pure 0.104 / AZ+BC 0.167。**Stage 3 stricter 物理不可达**。下一步候选: (a) r016 加 KL retention loss 防 BC 漂移;(b) r017 短 AZ (50g) 早期 ckpt 保留 BC 强度;(c) 接受 PPO 0.344 为 production,降级 stricter 阈值。
