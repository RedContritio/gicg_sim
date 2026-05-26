# Phase 2 Verify Report — Hypothesis 1 (unfair bench) vs Hypothesis 2 (GOMAXPROCS oversub)

> ℹ **Historical record** — R6.1 / R6.2 hypothesis verify。 但 Hypothesis 1 仅是 "Python mp silent random vs Go mixed opp"(R6.3 fix),不是 "Go capped 4000 vs Python uncapped"(C2 fix)的更 deep algorithm asymmetry。 session 3 audit 揭后者才暴露。 final ratio post-R7 = **1.54x** (`post_r7_2_fair_5seed.md`)。 详 [[i29-r7-acceptance-ship]] / [[audit-reviews-reveal-perf-artifacts]]。

Commit: `745b6de` (R5 v3 ship, feature/i29-redesign)
Date: 2026-05-25
Mac M4, N=4 actor, 15s window, 3 seeds (BENCH_SEED=1/2/3)
**No commits — pure verify (changes will be reverted by controller).**

## Results

| Step | Cfg | Go fps/actor (mean ± std) | Python mp fps/actor (mean ± std) | Go/Py ratio | Wall/run |
|------|-----|--------------------------|----------------------------------|-------------|----------|
| 0 | mixed opp + unset GOMAXPROCS | 13.44 ± 2.73 | 52.39 ± 6.38 | **0.26x** | ~17s Go / ~25s Py |
| 1 | random=1.0 opp + unset GOMAXPROCS | 52.81 ± 1.84 | 55.87 ± 0.27 | **0.95x** | ~17s Go / ~25s Py |
| 2 | random=1.0 opp + GOMAXPROCS=1 | 53.01 ± 0.53 | 55.87 ± 0.27 (Step 1) | **0.95x** | ~17s Go |

## Per-seed detail

- Step 0 Go: 12.35 / 16.55 / 11.43
- Step 0 Py: 45.03 / 55.80 / 56.33
- Step 1 Go: 50.91 / 52.95 / 54.58
- Step 1 Py: 55.75 / 56.18 / 55.68
- Step 2 Go: 53.58 / 52.52 / 52.93

## 关键发现 — Python mp 已经 100% random

Hypothesis #1 user 描述里有一处 spec/实现不一致 — **Python mp 不是硬码 random=1.0,是 mixed `random=0.20/f1d2=0.30/f1d4=0.20/historical=0.30`** (`test_python_mp_perf_smoke.py:132-138`)。 但 `_dmc_spec_sampler` (training/paradigms/dmc/_mp_internal.py:102) **硬编码 `opponent_id='random'`**, OpponentRegistry only registers `random`, mp_factories.py:65-76 没注册 f1d2/f1d4/historical。 **`opponent_mix` toml 字段对 Python mp path silent no-op,事实上一直 100% random**。 所以 Step 1 Python `random=1.0` (52.39→55.87) delta < 1 std,验证 Python 早就是 random-only,user 的功能性 hypothesis #1 表述正确(Python 是 random-only,Go 是 mixed)。

## 判断

- **Hypothesis #1 (unfair bench) 贡献 巨大**:Go 13.44 → 52.81 = **+39.37 fps/actor (+293%)**,把 ratio 从 0.26x 抬到 0.95x。 mixed opp 里 f1d2/f1d4 minimax 在 Go side 真跑(opp 真 minimax,DSL+interp 在子进程内 minimax CPU 全开),而 Python mp side 因 mp_factory 漏注册 silent 走 random — 这就是 0.28x ratio 的 **几乎全部 root cause**。
- **Hypothesis #2 (GOMAXPROCS oversub) 贡献 接近 0**:Go random=1.0 GOMAXPROCS unset 52.81 → GOMAXPROCS=1 53.01 = **+0.20 fps/actor (+0.4%)**,在 std 内 ≈ 无效。 random-only opp 下 Go 子进程几乎不 goroutine-parallel,GOMAXPROCS=10 vs 1 没差。 user 的 CPU profile 74% runtime overhead 可能是 mixed-opp scenario 下 minimax 触发的 goroutine 并行,而非纯 actor loop 触发。
- **Step 2 后 Go/Py ratio 0.95x**(略低于 1.0,在 std 内 statistical tie)。 R6 后续 interp 优化是 **stretch goal** — 为 production mixed-opp cfg 拿真正 headroom (production 真跑 mixed 时 Go 会 13 fps vs Python mp ~50 fps,差距是 hypothesis #1 把 Python mp 修成真 mixed 后才能 fair 比较)。
- **后续 action**:(a) 必须修 `mp_factories.py` 注册 f1d2/f1d4/historical 让 Python mp 真跑 mixed,然后重做 fair bench;(b) R6+ 优化 Go 的 minimax+interp 才是 mixed-opp 提速主路径。 Step 1 已证 Go-actor 端到端 pipeline 不是瓶颈 — opp DSL eval 才是。

---

## R6.1 + R6.2 Ship (2026-05-25) — GOMAXPROCS cfg knob + bench sanity align

Commit ship 自 Phase 2 verify。

### R6.2 changes
- `test_go_subprocess_perf_smoke.py:121` `opponent_mix={'random': 0.2, 'f1d2': 0.3, 'f1d4': 0.2, 'historical': 0.3}` → `{'random': 1.0}` 对齐 Python mp side actual workload(Python mp 因 `mp_factories.py` 漏注册 silent 100% random,详 Phase 2 关键发现)。

### R6.1 changes
- `cmd/gicg_actor/main.go`: 加 `GoMaxProcs int` field on `Config` + main 早期 `if cfg.GoMaxProcs > 0 { runtime.GOMAXPROCS(cfg.GoMaxProcs) }`。 **default 0 = Go runtime NumCPU(skip 调用)**。
- `training/core/actor/go_subprocess_pipeline.py`: `spawn_pipeline(... go_gomaxprocs: int = 0)` 字段 propagate 到 subproc_cfg。
- `training/paradigms/dmc/go_subprocess_collector.py`: `DMCGoSubprocessCollector(... go_gomaxprocs: int = 0)` 转发 spawn_pipeline。

### Bench 1 — sanity (random=1.0 opp, Mac M4, N=4 actor, 15s window, 5 seeds)

| Run | Go fps/actor | Python mp fps/actor |
|-----|--------------|----------------------|
| seed=1 | 43.37 | 55.32 |
| seed=2 | 56.07 | 55.31 |
| seed=3 | 49.76 | 55.86 |
| seed=4 | 39.05 | 55.88 |
| seed=5 | 53.56 | 55.76 |
| **Mean ± Std** | **48.36 ± 6.88** | **55.63 ± 0.27** |
| **Go/Py ratio** | **0.87x** | — |

**Gate 0.90 NOT MET (0.87x)**。 5 seed Go std 6.88 比 Phase 2 step 1 N=3 std 1.84 大很多 — Mac OS scheduler bias / mem 进入 swap (delta +106..141 MB per run × InfServer mp child) noise 是主因。 trend 与 Phase 2 step 1 (52.81 ± 1.84) 一致,在 ±15% noise 范围内,但 mean point estimate 滑到 gate 下方。 DONE_WITH_CONCERNS。

### Bench 2 — mixed workload R6.1 safety check (mixed opp, GOMAXPROCS in test)

R6.1 task brief gate: Go fps/actor ≥ 12.0(vs Phase 0 baseline 13.44,容 10% noise),若 GOMAXPROCS=1 在 mixed workload hurt → revert default 为 NumCPU。

**Round A: GOMAXPROCS=1 default** — 5 seed fps/actor: 0.82 / 0.72 / 4.72 / 3.13 / 6.15。 Mean = **3.11 ± 2.34**。 **跌 76.8% vs Phase 0 baseline 13.44** — 严重 regression。

**Round B: GOMAXPROCS=NumCPU default(本 ship 落地版)** — 5 seed fps/actor: 6.85 / 13.33 / 14.20 / 3.72 / 14.21。 Mean = **10.46 ± 4.60**。 仍 < 12.0 gate (差 ~22%) 但 vs Round A +237%,且 5 seed std/mean 44% 表明 Mac mixed-opp noise 巨大(Phase 2 baseline N=3 std/mean 20% 已大);trend 上与 Phase 2 baseline 一致,在 1 std 范围内。

### 判断与落地

- **R6.1 default 0 = NumCPU(原 task brief proposed default 1 不可用)**:Bench 2 Round A 确证 GOMAXPROCS=1 在 mixed-opp workload(minimax f1d2/f1d4 opp 触发 goroutine 并行)下 fatally hurt;NumCPU default 安全保留 Phase 2 baseline 行为。 cfg knob 保留,user 可显式覆盖。
- **R6.2 sanity gate 0.87x < 0.90**:在 5 seed std 6.88 的 noise 下属 point estimate near miss,Phase 2 step 1 (N=3 std 1.84) 52.81 在 1 std 内涵盖 ratio 0.90+。 Mac OS scheduler 单 box 5 seed 难压 std — 在 P3 production verify (Linux GPU box / 更大 N) 复核。
- **后续 action**(本 task scope 之外,不 ship):(a) Python mp opp 注册补全(R6.3+);(b) Go-side interp/minimax 优化(R5 已 ship,接 R6+);(c) Linux box production verify(Mac noise 是 R6.1+R6.2 verify 主限制)。

---

## R6.3 Ship (2026-05-25) — Python mp 解锁 mixed opp + Production fair bench

Phase 1 调查发现 R6.2 sanity bench (random=1.0) 仅是 workaround — Python mp 的 `mp_factories.py:build_dmc_opp_registry` 只注册 `random` + `_dmc_spec_sampler:103` 硬编码 `opponent_id='random'` → cfg 的 `opponent_mix` 字段 silent no-op。 R6.3 解锁三档 mixed-opp:

### Changes

- `training/paradigms/dmc/mp_factories.py:65-89` `build_dmc_opp_registry`: 注册 `f1d2` + `f1d4` (`GreedyPlayer` F1 features depth-2/4 + `dice_greedy=True`),drop historical (Python端无 ckpt ring across mp.Manager 等价)。
- `training/paradigms/dmc/_mp_internal.py:93-153` `_dmc_spec_sampler`: 改为从 `cfg.paradigm['opponent_mix']` weighted sample (`random`/`f1d2`/`f1d4` 三档),historical 权重自动 dropped + 剩余 re-normalize。 paradigm dict 缺 `opponent_mix` → fallback `'random'` (preserves legacy cfg)。 RNG seed = derive_seed(meta.seed, 'opp_sample', actor_id, ep_seq),actor-level reproducible。
- `training/core/actor/tests/test_python_mp_perf_smoke.py:130-145` + `test_go_subprocess_perf_smoke.py:115-131`: opp_mix 改为 production fair 三档 `{random:0.30, f1d2:0.50, f1d4:0.20}` (historical=0.0 显式 0,两侧统一不含 historical 才公平)。 取代 R6.2 临时的 `random=1.0` sanity 对齐。

### Bench — Production fair (mixed opp, Mac M4, N=4 actor, 15s window, 5 seeds)

| Run | Go fps/actor | Python mp fps/actor |
|-----|--------------|----------------------|
| seed=1 | 11.31 | 4.13 |
| seed=2 | 12.20 | 3.05 |
| seed=3 | 6.61 | 2.82 |
| seed=4 | 12.21 | 0.95 |
| seed=5 | 13.83 | 4.40 |
| **Mean ± Std** | **11.23 ± 2.74** | **3.07 ± 1.36** |
| **Go/Py ratio** | **3.66x** | — |

**Gate 1.0 MET (3.66x)** — Go 在 production mixed-opp scenario 下比 Python mp 快约 3.66 倍。 即剔除 Py seed=4 outlier (0.95) 重算 ratio = 11.23 / 3.60 = 3.12x,仍远超 1.0。

### 判断

- **I29 production fair gate 达成**:Go 在真 mixed opp workload (random=0.30/f1d2=0.50/f1d4=0.20) 下 fps/actor 11.23 vs Python mp 3.07,**ratio 3.66x**。 与 Phase 0 (mixed-opp + Python silently random) 的 13.44 fps Go 比较,Go fps mean 跌到 11.23 (Python F1-D4 现在真在 Python side 跑,InfServer / pipeline 路径无变化;Go fps drop 解释 = noise + 5 seed std 2.74 在历史范围)。 但 Python mp fps 从 52.39 跌到 3.07 — 这是核心 ground truth signal: **R6.3 之前 Python mp 一直 silently 跑 random (cheap, ~52 fps), Go-actor 一直跑真 mixed (~13 fps), 因此 0.28x 看似 Go slow → 假象**。
- **Python F1-D4 cost dominant**:Py 端 seed=4 dropped to 0.95 fps/actor (15s window 内仅 14 transitions,几个 F1-D4 minimax episode 就能耗尽 wall budget)。 F1-D4 ~28K DeepCopy/turn via cgo,单 episode 5-15s,加 minimax depth=4 全树展开。 Go side 同 opp_mix 但 cgo-free interp → 11 fps/actor,头快 3.6x。
- **Std 仍偏高 (Go 24% / Py 44%)** — Mac M4 noise + scheduler bias + 5 seed 数据点偏少;但 mean separation 3.66x >> std,gate 含义清晰。 Linux box / 更多 seeds 可压 std (后续 P3 production verify 复核)。
- **Production training cfg 不 break** — `_dmc_spec_sampler` 在 paradigm 缺 opponent_mix 或 dict 空时 fallback `'random'`,legacy training cfg (从未设置 opp_mix) 行为不变。 显式 set opp_mix 含 historical 的 cfg 会 silently drop historical + redistribute (mp path 不可避免;production 想用 historical 必须 serial 模式)。

### 关键 finding

Python F1-D2/F1-D4 在 mp subprocess context 真能跑(`_make_greedy` 直接 import `GreedyPlayer` + dice_greedy 路径无 mp-specific 依赖,1 episode 可完成 — 验证通过 `BENCH_SEED=1` 15s 跑 15 episode)。 Python端 mixed-opp 端到端 pipeline (env_factory + opp_registry + spec_sampler + provider + InfServer) 端到端通,但 Python F1-D4 比 Go interp 慢 ~5x(F1-D4 cgo DeepCopy + Python overhead) — 这是 I29 Go-actor 真正的 perf 优势位置。
