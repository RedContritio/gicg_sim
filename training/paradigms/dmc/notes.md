# DMC for GICG · Notes

> 运行观察 + decision changelog。详细 step 见 [PLAN.md](PLAN.md)。

## 整体进度

| Phase | Status | Wall-time | GPU-h | 关键数据 |
|---|---|---|---|---|
| 设计落定 | DONE 2026-05-12 | — | 0 | 8 个 decision 全 settled |
| 3.1 — DMC core 实现 | **DONE 2026-05-14** | ~1h | 0 | ~1280 LOC across 13 files,Mac smoke verified |
| 3.2 — Cross-platform engine + adapter | pending (Windows side) | — | 0 | libgicg.dll + TCP socket (Phase 3.5 prerequisite) |
| 3.3 — Eval 协议实现 | **DONE 2026-05-14** | ~30min | 0 | gen_eval_scenarios + periodic_eval,smoke 4 round 验证 |
| **3.4 — Mac smoke + eval verify** | **DONE 2026-05-14 03:44** | 5 min wall + ~1h dev | 0 | 136 ep / 5035 frames / 549 train steps,loss 0.95→0.67,vs F1-D2 WP 0→0.125 directional |
| **3.4.5 — CPU profile + 优化** | pending (Windows GPU 前必做) | ~半天 | 0 | per-actor fps target,X3D 特定优化 |
| 3.5 — Stage 3 Windows train | pending (需先 3.2 + 3.4.5) | ~16-25h | 25-40 | vs F1-D2 ≥ 0.50 |
| 3.6 — Stage 4 train | pending | — | 40-60 | 变 team size + asymmetric |
| 3.7 — Stage 5 train | pending | — | 60-100 | v_phase2 full deck(deferred prerequisite)|

## Decision changelog

| Date | Decision | 原因 |
|---|---|---|
| 2026-05-12 | A1 logit-as-Q(非 A2 独立 Q-MLP)| GICG actor_critic 已 expressive,A1 50 LOC vs A2 300 LOC,inherit zero-shot encoding |
| 2026-05-12 | 30/30/10/30 opp mix(random/F1-D2/F1-D4/historical)| user 指出 pure self-play 漂移,需充分混合;F1-D4 cap 10% 因 throughput |
| 2026-05-12 | 3 stages(3/4/5),skip 0-2 | 0-2 已 PPO/AZ PASS,无重复价值 |
| 2026-05-12 | Stage 3 = asymmetric(无 mirror)| user 指出 mirror 是少数 case + 已 documented degenerate |
| 2026-05-12 | Stage 4 变 team size + asymmetric char | user 加,真实 GICG 1/2/3 都合法,反应自然 emerge |
| 2026-05-12 | 每 stage PASS criteria = vs F1-D2 WP ≥ 0.50 | user 目标 "不劣于 greedy",对照 F1-D2 vs F1-D2 control 0.54 |
| 2026-05-12 | Windows native(非 WSL2)+ libgicg.dll | user 选 native;TCP localhost 替换 Unix socket(顺便 fix Gap 3 silent fail) |
| 2026-05-12 | In-repo `training/dmc/`(非隔离) | 与 `training/az/` `training/cfr/` 同级,共用 framework |
| 2026-05-12 | Lazy periodic eval(每 1h, n=128+swap, F1-D2 + F1-D4) | user 加,fixed seed scenarios + double-side 消 turn order bias |
| **2026-05-12** | **充分 CPU 优化(per-actor 单线程 + 进程 affinity + JIT inference + shared mem replay buffer)** | **user 加,确保 9950X3D X3D V-Cache 优势发挥** |

---

## CPU 优化目标(per Phase 3.4.5)

### per-actor 吞吐 target

类比 DouZero Phase 2 数据:
- H20 EPYC 9K84 单 actor 830 fps(45 actor × 830 ≈ 37500 total)
- **X3D 预期单 actor 1500-1800 fps**(V-Cache + 单核更强)
- **GICG DMC 预期(per actor)** 类似量级 — gicg_env step 比 DouDizhu rlcard env 复杂,可能略低,**~1000-1500 fps per actor**
- Target:24 actor × 1200 fps = **~28800 fps 总**,16h 内跑 1.6e9 frames

### per-actor 设置 checklist

每 actor process 启动时(in `train_loop.py` actor function 头部):

```python
import os
os.environ["OMP_NUM_THREADS"] = "1"          # MKL/OpenMP per process
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import torch
torch.set_num_threads(1)                      # PyTorch CPU thread
torch.set_num_interop_threads(1)

import numpy as np
# numpy 通过 OMP env var 已限制
```

### 进程 affinity(Windows X3D 特定)

X3D CCD layout(理论):
- CCD0: cores 0-7,**含 96MB V-Cache**,单核 boost 较低
- CCD1: cores 8-15,无 V-Cache,单核 boost 较高(5.7GHz)

DMC actor 特点:hot working set ~几 MB(LSTM weights + recent state),**全 fit V-Cache**:

| Process | Affinity | 理由 |
|---|---|---|
| **Actors(24 个)** | **CCD0 cores 0-7 优先(SMT pair 共 16 logical),溢出到 CCD1** | V-Cache 命中率 max,24 actor 在 16 logical CCD0 略 oversubscribe 但工作负载 IO bound + low NUMA penalty |
| **Learner thread** | **CCD1 single core(e.g. 8)** | learner 单线程串行,V-Cache 不重要 |
| **Eval process** | **CCD1 cores 8-15** | 与 actor 物理隔离,避免 cache contention |

实装:
```python
import psutil
p = psutil.Process()
# actor process
p.cpu_affinity([0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23])  # CCD0 16 logical
# learner
p.cpu_affinity([8])
# eval
p.cpu_affinity([9, 10, 11, 12, 13, 14, 15])
```

实测后调,看 cache miss rate(`Process Explorer` 或 Linux `perf` 类工具)。

### Inference 路径优化

- **torch.inference_mode()** 取代 no_grad(更激进 — 跳过 view tracking)
- **torch.jit.trace** 编译 actor forward 一次,后续直接调 JIT 路径
- **避免 .cpu().numpy() 频繁切换** — actor 全程 CPU,no device 转换

```python
# actor 启动后,trace 一次
example_obs = ...
traced_net = torch.jit.trace(net, example_obs)
# 后续 act loop:
with torch.inference_mode():
    logits = traced_net(*obs_args)
```

### Replay buffer(进程间 shared)

- **`multiprocessing.shared_memory`** 替代 mp.Queue 大 tensor pass(避免 pickle/unpickle 开销)
- DouZero 用 `mp.SimpleQueue` for small metadata + shared tensor block for big data — 可借鉴
- Pre-allocate fixed-size buffer:N_buffers × max_episode_len × obs_dim

### Engine 调用频次

`gicg_engine` capi 调用通过 ctypes,**单调用 ~1-5μs overhead**(Mac 实测,Windows 类似)。
- step / clone / get_legal_actions / get_obs 各一次/turn → 总 ~10-30μs engine overhead / step
- 与 NN forward(~100-500μs / step)相比是小头,但 hot loop 不要冗余调

### 整体期待

| 优化 | 单 actor fps 影响 |
|---|---|
| OMP_NUM_THREADS=1 | +50× (oversubscription removal) |
| inference_mode + jit | +10-30% |
| Affinity + V-Cache hit | +20-40% on X3D |
| Shared memory replay | +5-15% |
| **总 expected** | **~1500-2000 fps per actor on X3D** |

Phase 3.4 smoke 实测验证,Phase 3.4.5 投入半天优化。Phase 3.5 训前固化最佳 config。

---

## Paper vs Impl observations

(发现 DouZero paper / DMC paradigm 与 GICG 实际不符,在这里记录)

(待 Phase 3.1+ 实测后填)

---

## Phase 3.1 — implementation observations

(待开工)

---

## Phase 3.4 — Mac smoke results · DONE 2026-05-14 03:44

**Run**: `artifacts/202605140344_dmc_stage3_smoke/`
**Config**: `configs/dmc_stage3_smoke.toml`(d_model=32 / batch=16 / total_frames=5000 / eval n=4 + swap)

### Final summary

```json
{"frames": 5035, "episodes": 136, "train_steps": 549,
 "wins": 76, "losses": 52, "draws": 8, "wall_s": 294.92}
```

136 episodes / 5035 frames / 549 train steps in ~5 min on Mac M-series CPU(single process,F1-D4 disabled因 cost too high)。

### Pipeline ✓

- Config load (TOML + base preset overrides) ✓
- Env reset + episode play(包含 PHASE_SELECT_ACTIVE skip + opp 切换)✓
- Agent forward (logit-as-Q) + ε-greedy ✓
- Replay buffer push + sample ✓
- Train step (MC return + MSE loss + AdamW) ✓
- Periodic ckpt(每 2 min)✓
- Periodic eval(每 1 min)✓

### Loss trajectory

```
step  50: 0.95
step 100: 0.82
step 150: 1.13   (噪声)
step 200: 0.65
step 250: 0.85
step 500: 0.67
step 549: 0.67   (final)
```

MSE 在 0.6-1.1 噪声区间(target ±1,baseline ~1.0)。趋势 **0.95 → 0.67**,下降明显。

### Eval trajectory(vs F1-D2,n=8 = 4 + 4 swap)

| Round | wall_s | frames | WP_mean | swap_p0 | swap_p1 | CI95 |
|---|---|---|---|---|---|---|
| 1 | 62 | 1035 | 0.000 | 0.000 | 0.000 | [0.00, 0.32] |
| 2 | 123 | 2119 | 0.125 | 0.250 | 0.000 | [0.02, 0.47] |
| 3 | 184 | 3216 | 0.125 | 0.250 | 0.000 | [0.02, 0.47] |
| 4 | 247 | 4250 | 0.125 | 0.250 | 0.000 | [0.02, 0.47] |

**0 → 0.125 in 4250 frames** = directional signal exists。但 n=8 noise floor 大(CI95 跨 0.02-0.47),不严格可判。

Swap p0/p1 asymmetry(0.25 vs 0.00):p0 = agent=赤蝶 / opp=墨客;p1 反过来。0.25 vs 0.00 显示**赤蝶 side 单局赢了 1/4**,墨客 side 0/4。与 s068 documented F1-D2 vs F1-D2 control 0.54 asymmetric 一致(angle-dependent)。

### Win/loss mix(全 episodes including random + F1-D2 opp)

- vs random:多胜(直觉:agent 在 5k frames 已学一些 skill 选择)
- vs F1-D2:多败(directional consistent with eval)
- Overall:76 W / 52 L / 8 D / 56% win rate over mixed opp(opp pool 40% random + 30% F1-D2 + 30% historical)

### Phase 3.4 PASS criteria 复核

| Item | criterion | actual | PASS? |
|---|---|---|---|
| Loss 下降 | 不 NaN + 趋势降 | 0.95 → 0.67 ✓ | ✅ |
| Mean ep return 翻正 / 移动 | 至少 from negative 走向 0 | overall +0.18(76 W - 52 L)/ 136 ep | ✅ |
| Eval swap_sides 对称 | n_games 双向,p0/p1 数值不应**系统性偏向**(若 ≥ 0.1 偏差 = bug) | 0.25 vs 0.00 偏向 — 但 8 games CI 大,且 s068 asymmetric matchup 本身有 turn bias,**不算 bug** | ✅ (qualified) |
| Eval frequency | 1 min × 5 min run = 4-5 eval | 4 eval ✓ | ✅ |
| metrics.jsonl format | 每 line valid JSON,含 vs_<baseline> | ✓ | ✅ |
| CI 计算 | Wilson p=0.125,n=8 CI [0.02, 0.47] | ✓ | ✅ |
| vs F1-D2 directional | > 0.10 super random / mutual 0 | 0.125 ✓ | ✅(noise floor 内但 > 0) |

**Phase 3.4 PASS — 仅指 pipeline OK(loss / replay / eval / ckpt / opp pool)。**

> **⚠ review D.1 修正(2026-05-14)**:smoke 跑的 vs F1-D2=0.125 是 n=8 noise floor 内信号,**不**作为 "DMC paradigm 在 GICG 上 work" 的判据。真正能否 work 看 Stage 3 pilot (100k+ frames) 上 Mac daemon eval n=128 × 2 sides 的 wp_mean。Smoke 只能验证 "pipeline 不崩 + 数据流正确"。

### 已知限制(留 Phase 3.5 优化)

1. **F1-D4 opp 在 smoke 中禁用**(`f1d4=0.0`)— GreedyPlayer validation 已 patch 支持 D4,但单调用慢(~1-2 sec/decision)。Stage 3 full train 上,10% 比例 F1-D4 可吞 (throughput 影响 ~5-10%)。Phase 3.5 上 X3D 实测决定 final ratio
2. **Single-process 单 actor**:smoke 跑 17 fps,远低于 DouZero phase 2 X3D 预估 30k+ fps。Phase 3.5 上 multi-process spawn(`torch.multiprocessing` 直接借 DouZero `dmc/utils::act` 模式)
3. **Replay buffer 存 full static obs / transition**:memory 浪费,Phase 3.5 改 game_id dedup(framework.buffer.StaticDedupBufferBase 现成基设施)
4. **Eval env 每 scenario new GicgEnv**:慢(0.8 sec/eval round × 4 scenarios)。Stage 3 fixed teams 可 reuse 一个 env,只 reset(seed=) — Phase 3.5 优化
5. **Agent.game_start 跨 train/eval cache pollution**:目前依赖每 episode 新 game_start 重置 cache。Phase 3.5 multi-process 隔离后不再是问题(eval 自己的 agent 进程)

### TensorBoard 集成(decision #10,2026-05-14 04:49)

每 run 在 `artifacts/<run>/tb/` 写 TB event 文件。**12 个 scalar tag**:

| Group | Tags | Points / 5K-frame smoke |
|---|---|---|
| `train/` | `loss`, `grad_norm` | 每 train step (526) |
| `train/` | `fps` | 每 10 episode (13) |
| `episode/` | `return_G`, `return_mean100`, `win_rate_100`, `n_steps`, `buf_size` | 每 episode (135) |
| `eval/` | `F1-D2_wp_mean`, `wp_swap_p0`, `wp_swap_p1`, `ci95_width` | 每 eval round (4) |

加 `add_hparams` 把 lr / batch_size / d_model / total_frames / epsilon 与 final win_rate 一起记录,可在 TB HPARAMS tab 看(适合后续 hparam sweep)。

查看:
```bash
.venv/bin/tensorboard --logdir artifacts/<run>/tb --port 6006
# 浏览器打开 http://localhost:6006
```

或集合多 run 对比:
```bash
.venv/bin/tensorboard --logdir artifacts --port 6006
```

### Code 增量

| 文件 | LOC | 状态 |
|---|---|---|
| `training/dmc/__init__.py` | 9 | 落定 |
| `training/dmc/config.py` | ~150 | 落定 |
| `training/dmc/config_loader.py` | ~70 | 落定 |
| `training/dmc/opponent_pool.py` | ~90 | 落定 |
| `training/dmc/replay.py` | ~55 | 落定 |
| `training/dmc/loss.py` | ~40 | 落定 |
| `training/dmc/agent.py` | ~190 | 落定 |
| `training/dmc/train_loop.py` | ~420 | 落定(含 TB 集成) |
| `training/dmc/eval/__init__.py` | 1 | 落定 |
| `training/dmc/eval/gen_eval_scenarios.py` | ~65 | 落定 |
| `training/dmc/eval/periodic_eval.py` | ~180 | 落定 |
| `tools/dmc_train.py` | ~30 | 落定 |
| `configs/dmc_stage3_smoke.toml` | ~40 | 落定 |
| **Total new** | **~1280 LOC** | smoke-verified |
| `training/framework/matchup/greedy_player.py` | +1 LOC(D4 support patch) | 落定 |

---

## Phase 3.4.5 — CPU profile results

(待 profile + 优化后填)

---

## Phase 3.5 — Stage 3 Windows train results

(待训练后填)

---

## Phase 3.5 Windows GPU box — connection + environment (2026-05-14)

### SSH access

```bash
ssh dev@192.168.31.56          # LAN,无密码(key-based)
```

Hostname:`DESKTOP-GHJCC7Q`(9950X3D + 5070 Ti box)

### 路径约定

| 用途 | 路径 |
|---|---|
| Project root | `D:\gicg_dev\` |
| venv | `D:\gicg_dev\.venv\` |
| venv Python | `D:\gicg_dev\.venv\Scripts\python.exe` |
| Engine .dll | `D:\gicg_dev\gicg_env\libgicg.dll`(已 build) |

### 工具链版本

| 工具 | 版本 / 位置 |
|---|---|
| Python | 3.13.5(`C:\Python313\python.exe`) |
| Go | 1.24.5(`C:\Program Files\Go\bin\go.exe`) |
| Git | 标准 Git for Windows |
| gcc(for cgo) | Strawberry Perl 自带 `C:\Strawberry\c\bin\gcc.exe` |
| nvidia driver | 596.36 |
| GPU | RTX 5070 Ti(Blackwell,sm_120,16 GB)|
| PyTorch | **2.12.0+cu130 stable**(支持 Blackwell sm_120 — cu126 build 不支持) |

### Build engine on Windows

```powershell
$env:CGO_ENABLED = "1"
$env:CC = "C:\Strawberry\c\bin\gcc.exe"
$env:PATH = "C:\Strawberry\c\bin;" + $env:PATH
cd D:\gicg_dev
go build -buildmode=c-shared -o gicg_env\libgicg.dll .\gicg_engine\capi\
```

build 时间 ~30 秒。产物 `D:\gicg_dev\gicg_env\libgicg.dll`。

### 同步代码 Mac → Windows

```bash
# 从 Mac 推 code-only tarball(~37 MB),排除 artifacts / .venv / ref
cd ~/Projects/gicg_mono
tar -czf - \
  --exclude=artifacts --exclude=.venv --exclude=ref --exclude=__pycache__ \
  --exclude='.git' --exclude='*.pyc' --exclude='gicg_env/libgicg.dylib' \
  --exclude='gicg_env/libgicg.h' \
  -C ~/Projects/gicg_mono . | \
  ssh dev@192.168.31.56 'powershell -Command "cd D:\gicg_dev; tar -xzf -"'

# 清 macOS metadata
ssh dev@192.168.31.56 'powershell -Command "Get-ChildItem D:\gicg_dev -Recurse -Force | Where-Object {\$_.Name -like \"._*\" -or \$_.Name -eq \".DS_Store\"} | Remove-Item -Force"'
```

### Python venv 安装

```powershell
cd D:\gicg_dev
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
# Blackwell 需 cu130 build,cu126 build 仅支持到 sm_90
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install tensorboard
```

### Verify CUDA 通

```powershell
.\.venv\Scripts\python.exe -c "import torch; print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available()); x = torch.randn(8,8, device='cuda'); print('forward OK:', (x@x.T).shape)"
# 预期: torch: 2.12.0+cu130 / cuda: True / forward OK: torch.Size([8, 8])
```

### Verify smoke 流程通(config_loader + env import)

```powershell
cd D:\gicg_dev
$env:OMP_NUM_THREADS = "1"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -X utf8 -c "from training.dmc.config_loader import load_config; cfg = load_config('configs/dmc_stage3_smoke.toml'); print('cfg OK', cfg.run_label, cfg.total_frames)"
# 预期: cfg OK dmc_stage3_smoke 5000
```

✅ Verified 2026-05-14 — config 加载 + cuda 转发都通,sm_120 兼容确认。

### 下一步(Phase 3.5 实际训练)

待办:
1. Windows 上跑一次 Mac smoke 等价 cfg,验证端到端 work
2. 决定 multi-process actor 还是 single-process(本 smoke 单进程,Windows GPU 可考虑多 actor)
3. CPU affinity 调:CCD0 cores 0-7 给 actors(V-Cache),CCD1 给 learner / eval
4. Stage 3 full train(2e9 frames 量级 / 25-40 GPU-h)

### 注意 / 已知坑

- **PowerShell SSH 编码**:Windows cmd `dir` 中文输出乱码;改用 PowerShell 命令拿目录信息
- **PowerShell 多行命令通过 stdin pipe**:用 `cat << 'EOF' | ssh dev@... 'powershell -Command -'` 模式,避免 quote escape 问题
- **`PYTHONIOENCODING=utf-8` + `python -X utf8`**:中文角色名/卡牌名涉及 UTF-8,Windows 默认 cp936,需显式 UTF-8 mode
- **Blackwell sm_120 必须 cu130 build**:cu126 + 5070 Ti 跑 → "compute capability sm_120 not compatible"

---

## 关键 link

- DouZero repro: `~/Projects/Research/douzero_icml2021/` (Phase 0/1/2 PASS,paper -8% gap)
- DouZero dmc source 参考: `~/Projects/Research/douzero_icml2021/original/DouZero/douzero/dmc/`
- s068 baseline: `docs/5_history/runs_pre_redesign_2026_05_17.md`(asymmetric AZ pure 0.271 ± 0.078)
- F1-D2 反例: `tools/test_dice_scheduling.py`(Scenario 3 buff-before-skill ordering, 1 char 可触发)
- ADR-0006 training layout: `docs/2_decisions/adr-0006-training_layout.md`
