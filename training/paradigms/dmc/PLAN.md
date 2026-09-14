# DMC for GICG · Implementation Plan

> **历史设计快照（2026-05）**：本文用于解释 DMC 的原始分阶段设计，
> 其中路径、socket 方案和 pending 状态均是当时记录。当前实现以
> `training/paradigms/dmc/`、`training/core/` 和 OpenSpec LIVE spec
> 为准。

> Step-by-step。每 Phase 完成更新 [README.md](README.md) status + [notes.md](notes.md) observations。

## Phase 3.1 · DMC core implementation(Mac dev,~200 LOC,1-2 day)

**Goal**:实现 DMC 训练算法,复用 GICG framework + actor_critic 网络。

### 3.1.1 · `config_loader.py`(~50 LOC)

类比 `training/az/config_loader.py`:`DmcConfig` dataclass + TOML loader。

关键 cfg 字段:
```python
@dataclass
class DmcConfig:
    # Training
    total_frames: int = 100_000_000
    batch_size: int = 32
    learning_rate: float = 1e-4
    exp_epsilon: float = 0.01
    num_buffers: int = 50
    num_actors: int = 24            # Windows 9950X3D: 24 / Mac smoke: 4-8

    # Scenario
    scenario: ScenarioSpec          # 沿用 framework
    opponent_pool: OpponentPoolSpec  # 新增

    # Eval
    eval_interval_minutes: int = 60
    eval_n_scenarios: int = 128
    eval_baselines: list[str] = ["F1-D2", "F1-D4"]
    eval_scenarios_seed: int = 42
```

### 3.1.2 · `opponent_pool.py`(~80 LOC)

实现 30/30/10/30 mixed opponent:

```python
class OpponentPool:
    def __init__(self, weights, historical_ring_size=20):
        self.weights = weights        # {"random": 0.30, "F1-D2": 0.30, "F1-D4": 0.10, "historical": 0.30}
        self.ring = deque(maxlen=historical_ring_size)

    def sample(self) -> Player:
        """每 episode start 调用一次"""
        kind = weighted_choice(self.weights)
        if kind == "random":
            return RandomPlayer()
        elif kind == "F1-D2":
            return GreedyPlayer(features='F1', depth=2, dice_greedy=True)
        elif kind == "F1-D4":
            return GreedyPlayer(features='F1', depth=4, dice_greedy=True)
        elif kind == "historical":
            ckpt = random.choice(self.ring) if self.ring else self.current
            return DmcAgent(ckpt)

    def add_snapshot(self, ckpt):
        """每 N steps learner 调用,加入 historical ring"""
        self.ring.append(ckpt)
```

### 3.1.3 · `replay.py`(~30 LOC)

Replay schema 与 AZ 不同:

```python
@dataclass
class DmcTransition:
    obs: dict           # 完整 obs(static + dynamic + actions)
    action_idx: int     # 选择的 legal action idx
    episode_return: float  # G,episode 终局后 backfill
```

FIFO buffer,actor push,learner pop batch_size。complex multi-process shared queue 走 `multiprocessing.SimpleQueue`(同 DouZero)。

### 3.1.4 · `loss.py`(~30 LOC)

MC return + MSE on logit:

```python
def dmc_loss(net, batch):
    """
    batch: (obs, action_idx, G) dict of stacked tensors
    """
    logits, _, _ = net(**batch.obs)  # (B, N_act),复用 actor_critic.forward
    selected_logit = logits.gather(1, batch.action_idx.unsqueeze(1)).squeeze(1)  # (B,)
    loss = F.mse_loss(selected_logit, batch.G)
    return loss
```

注意:
- ignore `value` 和 `delta_pred` head 的输出(DMC 不用)
- 不做 PPO clip / advantage / GAE
- γ=1(sparse terminal,无 bootstrap)

### 3.1.5 · `agent.py`(~40 LOC)

DMC inference:

```python
class DmcAgent:
    def __init__(self, ckpt_path, epsilon=0.0):  # eval 时 ε=0
        self.net = load_actor_critic(ckpt_path)
        self.epsilon = epsilon

    def select_action(self, env):
        if random.random() < self.epsilon:
            return random.randrange(env.num_legal_actions())
        with torch.no_grad():
            logits, _, _ = self.net(**env.get_obs())
        return torch.argmax(logits).item()
```

### 3.1.6 · `train_loop.py`(~200 LOC)

Actor-learner async,直接 adapt DouZero `douzero/dmc/dmc.py` 框架:
- N actors(spawn process):pull weights → play episode → push transitions
- 1 learner thread:pop batch → forward + loss + backward → push weights snapshot
- 共用 framework.matchup 的 env wrapper

**关键**:`--actor_device_cpu` 强制 actor 跑 CPU(DouZero phase 2 验证 58× 加速),learner 在 GPU。

---

## Phase 3.2 · Cross-platform engine + adapter(~半天,~60 LOC + Windows build)

### 3.2.1 · Engine: libgicg.dll on Windows

在 9950X3D Windows 机上:
```powershell
# 装 Go(scoop install go)+ MinGW-w64(scoop install mingw)
set CGO_ENABLED=1
set CC=x86_64-w64-mingw32-gcc
go build -buildmode=c-shared -o libgicg.dll ./gicg_engine/capi/
```

### 3.2.2 · Python platform detect adapter(~10 LOC)

`gicg_env/engine.py`:
```python
import platform
ext = {'Darwin': 'dylib', 'Linux': 'so', 'Windows': 'dll'}[platform.system()]
lib_path = os.path.join(os.path.dirname(__file__), f'libgicg.{ext}')
```

### 3.2.3 · TCP localhost replace Unix socket(~50 LOC)

**路径校正(2026-05-18 audit)**:原 plan 指 `training/framework/inference/server_loop/server.py + client.py` 但该路径实际用 `multiprocessing.connection` Pipe(与 socket 无关)。**真正 Unix socket** 在 `tools/eval/eval_service.py:55`(client 读 `GICG_EVAL_SOCKET`)+ `tools/eval/eval_service_server.py:63`(`socket.AF_UNIX`)。

`tools/eval/eval_service{,_server}.py`:
- `socket.AF_UNIX` → `socket.AF_INET`
- 配置 `GICG_EVAL_PORT`(default 9100)+ `GICG_EVAL_HOST`(default `localhost`)替代 `GICG_EVAL_SOCKET` path
- 不留 `AF_UNIX` fallback(per `feedback_no_compat_fallback` memory)
- 顺便 fix memory `project_v_phase2_eval_schema_gaps` Gap 3 silent fail

Verify:Mac + Windows 上 `python -m pytest gicg_env/tests/ -q` 全 PASS。

---

## Phase 3.3 · Eval 协议实现(~120 LOC,~半天)

### 3.3.1 · `eval/gen_eval_scenarios.py`(~60 LOC)

```python
def generate_eval_scenarios(seed, n, team_size_dist, char_pool, card_pool):
    """Pre-generate n eval scenarios with fixed seed.
    
    每 scenario 包含:
    - team_size(双方相同,sampled from dist)
    - team_0_chars, team_1_chars(各独立 sampled)
    - initial_dice_seq(完整 per-turn 8-dice roll 序列,max_rounds × 2 player)
    - deck shuffle seed(双方)
    - initial hand draw seed
    """
    rng = np.random.RandomState(seed)
    scenarios = []
    for i in range(n):
        ts = rng.choice(list(team_size_dist.keys()), p=list(team_size_dist.values()))
        s = {
            'team_size': int(ts),
            'team_0': rng.choice(char_pool, size=ts, replace=False).tolist(),
            'team_1': rng.choice(char_pool, size=ts, replace=False).tolist(),
            'dice_seq_seed': int(rng.randint(0, 2**31)),
            'deck_seed_p0': int(rng.randint(0, 2**31)),
            'deck_seed_p1': int(rng.randint(0, 2**31)),
        }
        scenarios.append(s)
    return scenarios
```

输出 `eval_scenarios_stage{3,4,5}.pkl`。

### 3.3.2 · `eval/periodic_eval.py`(~60 LOC)

```python
class PeriodicEvaluator:
    def __init__(self, cfg, scenarios_path):
        self.scenarios = pickle.load(open(scenarios_path, 'rb'))
        self.baselines = [load_baseline(name) for name in cfg.eval_baselines]

    def run_once(self, agent_ckpt):
        """运行完整 eval round,return metrics dict"""
        agent = DmcAgent(agent_ckpt, epsilon=0.0)
        metrics = {}
        for baseline_name, baseline in zip(cfg.eval_baselines, self.baselines):
            wp_p0 = self._eval_side(agent, baseline, side=0)
            wp_p1 = self._eval_side(agent, baseline, side=1)
            metrics[f"vs_{baseline_name}"] = {
                "wp_mean": (wp_p0 + wp_p1) / 2,
                "wp_swap_p0": wp_p0,
                "wp_swap_p1": wp_p1,
                "n": len(self.scenarios) * 2,
                "ci_95": wilson_ci(...)
            }
        return metrics

    def _eval_side(self, agent, baseline, side):
        wins = 0
        for s in self.scenarios:
            # play one game with `side` mapping (0 or 1)
            outcome = play_scenario(s, agent, baseline, agent_side=side)
            wins += int(outcome == "agent_win")
        return wins / len(self.scenarios)
```

`periodic_eval.py` 跑独立 process,每 60 min 触发(看 metrics 时间戳决定 reset)。

### 3.3.3 · 集成到 train_loop.py

learner 每 N learn step 检查时间,如 >= eval_interval_minutes,fork 一个 process 跑 PeriodicEvaluator,**异步** —training 不阻塞,eval 用 spare CPU core。

---

## Phase 3.4 · Mac CPU smoke + eval 协议验证(2-4h,0 GPU-h)

**Goal**:验证整个 pipeline 端到端 work,**重点 verify eval 协议本身没 bug**(scenario gen / swap sides / metric logging)。

### 3.4.1 · Quick smoke train(~30 min)

```bash
.venv/bin/python -m tools.dmc_train configs/dmc_stage3_smoke.toml
```

cfg `dmc_stage3_smoke.toml`:
```toml
[training]
total_frames = 5_000_000
batch_size = 32
num_actors = 4         # Mac M-series
exp_epsilon = 0.01
learning_rate = 1e-4

[scenario]
# Stage 3 spec
team_size_random = [1]
char_pool = ["赤蝶", "墨客"]
card_pool = ["测试卡_增幅", "测试卡_碎片"]
obs_mask = ["enemy_dice"]
max_rounds = 5

[opponent_pool]
random = 0.30
"F1-D2" = 0.30
"F1-D4" = 0.10
historical = 0.30
ring_size = 20

[eval]
interval_minutes = 5       # smoke 缩短,看几次 eval round
n_scenarios = 32           # smoke 缩小
baselines = ["F1-D2", "F1-D4"]
scenarios_seed = 42
```

### 3.4.2 · Verify items

| Item | Pass criteria |
|---|---|
| Loss 下降 | logs.csv 中 loss 有趋势下降(不 NaN) |
| Mean ep return 翻正 / 移动 | 至少 from negative 走向 0 |
| Eval 协议:swap sides 对称 | wp_swap_p0 vs wp_swap_p1 在 random scenario 下数值不应系统性偏向(若有 ≥ 0.1 偏差,说明 swap 实现有 bug) |
| Eval frequency | 5 min × 6 = 30 min 中应出现 ≥ 4-5 个 eval point |
| metrics.jsonl 格式 | 每 line valid JSON,包含 frame / vs_F1-D2 / vs_F1-D4 字段 |
| CI 计算 | n=64(32+32 swap)的 Wilson CI 落在 ±10% 内合理 |

### 3.4.3 · Verify target(Mac CPU 5M frames)

类比 DouZero phase 1.4 directional signal:
- vs F1-D2 WP > 0.10(超 random opp pool 的 mutual 0.0073)— 看到 RL signal
- vs F1-D4 WP > 0.05(F1-D4 更强,gap 更大)
- 全部 0 → debug pipeline

5M frames Mac CPU ~30 min,**不要求 50%**(那是 Stage 3 full train Phase 3.5 目标)。

---

## Phase 3.4.5 · CPU 性能 profile + 优化(Mac smoke 后 / 上 GPU 前,~半天)

**Goal**:充分优化 per-actor CPU 吞吐,确保 9950X3D X3D V-Cache 优势在 Phase 3.5 训练中发挥。

### 3.4.5.1 · Per-actor 单线程基线(必做)

每 actor process 启动头部强制:

```python
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
```

DouZero Phase 2 实证:**OMP_NUM_THREADS=1 = 640 → 37500 fps(58×)**,fundamental requirement,不是 optional。

### 3.4.5.2 · 进程 affinity(Windows X3D 特定)

X3D CCD layout 利用:

| Process | Affinity | 理由 |
|---|---|---|
| 24 个 Actor | CCD0 cores 0-7(SMT pair 共 16 logical)+ 溢出 CCD1 cores 16-23 | V-Cache 命中,hot working set ~few MB fit 96MB L3 |
| Learner | CCD1 single core(8) | 单线程串行,V-Cache 不重要 |
| Eval | CCD1 cores 9-15 | 与 actor 物理隔离,避免 cache contention |

实装:
```python
import psutil
psutil.Process().cpu_affinity([0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23])  # actor
```

profile 后调,看 cache miss rate(Linux `perf stat` / Windows `Process Explorer`)。

### 3.4.5.3 · Inference 路径优化

```python
# actor 启动后 trace 一次,后续走 JIT
traced_net = torch.jit.trace(net, example_obs)

# Hot loop:
with torch.inference_mode():  # 比 no_grad 激进,跳过 view tracking
    logits = traced_net(*obs_args)
```

预期 +10-30% per-actor fps。

### 3.4.5.4 · Replay buffer shared memory

- `multiprocessing.shared_memory` 替代 mp.Queue 大 tensor pass(避免 pickle 开销)
- Pre-allocate fixed-size buffer:`N_buffers × max_episode_len × obs_dim`,actor index 写,learner index 读

实装:类比 DouZero `douzero/dmc/dmc.py::create_buffers`(直接 adapt)。

### 3.4.5.5 · Engine 调用 minimize

`gicg_engine` capi 单调用 ~1-5μs ctypes overhead。Hot loop 必要调用:
- `env.step(action_idx)` × 1/turn
- `env.get_legal_actions()` × 1/turn(after step)
- `env.get_obs()` × 1/turn

总 ~10-30μs engine overhead/step,与 NN forward(~100-500μs)相比小头。**不冗余调用即可**,不需要深度优化 engine。

### 3.4.5.6 · cProfile 验证

5 min single-actor run + cProfile:

```python
python -m cProfile -o actor.prof -m tools.dmc_train configs/dmc_stage3_smoke.toml --num_actors 1 --total_frames 100000

# 用 snakeviz 可视化
snakeviz actor.prof
```

Top 10 hotspots 应该是:
1. NN forward(~30-50%)
2. env.step + get_legal_actions(~15-25%)
3. tensor 转换 / numpy slice(~10-15%)
4. Python overhead(~5-10%)
5. 其它

**红线**:
- 任何 BLAS / OMP threading sync 调用 → OMP 设置漏了
- pickle / unpickle 在 hot path → shared memory 未生效
- 频繁 .to('cuda') / .cpu() → 没 keep CPU-only

### 3.4.5.7 · Target throughput

|   | Per-actor fps | Total fps(24 actors)| 16h frame |
|---|---|---|---|
| Naive baseline(无优化) | ~50-200 | ~1k-5k | ~6e7-3e8 |
| OMP_THREADS=1 only | ~800-1200 | ~20k-29k | ~1.2-1.7e9 |
| **+ Affinity + JIT + sharedmem(全优化)** | **~1500-1800** | **~36k-43k** | **~2.1-2.5e9** |

Phase 3.4.5 PASS criteria:per-actor ≥ 1200 fps + total ≥ 28k fps(允许 V-Cache 优势未完全发挥)。

---

## Phase 3.5 · Stage 3 Windows GPU full train(25-40 GPU-h)

### 3.5.1 · Bundle code to 9950X3D Windows

类比 DouZero Phase 2.0:
```bash
# Mac dev
cd ~/Projects/gicg_mono
tar czf phase3_5_bundle.tar.gz \
    training/ gicg_env/ gicg_engine/ data/pools/test_basic data/pools/v_phase2 \
    tools/dmc_train.py tools/gen_eval_scenarios.py configs/dmc_stage3.toml
# scp to Windows box
```

Windows 上 unbundle + `go build libgicg.dll` + venv install。

### 3.5.2 · Train(预计 16-25h wall on X3D + 5070 Ti)

```powershell
python -m tools.dmc_train configs\dmc_stage3.toml
```

cfg `dmc_stage3.toml`:
- `total_frames = 2_000_000_000`(类比 DouZero Phase 2 scaled-down 量级)
- `num_actors = 24`(X3D 32T - learner/eval reserve 8 thread)
- `gpu_devices = 0`(5070 Ti)
- 其它继承 smoke cfg

### 3.5.3 · 监控 + 早停

每 1h periodic eval 落 metrics.jsonl。**早停 criterion**:
- vs F1-D2 WP **持续 3 次 eval > 0.50** + vs F1-D4 不 collapse(> 0.30) → 早停,PASS
- 16h 内仍 < 0.30 → early abort + investigate

### 3.5.4 · Stage 3 Verdict 判定

|   | 解读 | 下一步 |
|---|---|---|
| WP ≥ 0.50 | DMC paradigm 在 GICG 1-char asymmetric verified | Phase 3.6 Stage 4 |
| 0.27 ≤ WP < 0.50 | 比 s068 (0.271) 强,paradigm 部分 work,未达 user target | hparam ablation(network capacity / actor count / opponent mix ratio)后 retry |
| WP < 0.27 | DMC ≈ AZ pure,paradigm-task fit 在 GICG 仍弱 | 考虑换 paper(NFSP / AlphaHoldem K-Best) |

---

## Phase 3.6 · Stage 4 train(40-60 GPU-h) · ⏸ PENDING Stage 3 验证

> **⚠ review F.2(2026-05-14)**:本节是 Stage 3 PASS 后才启动的 plan。Stage 3 失败(per A.3 高概率)→ Stage 4 设计废纸。本节内容**仅作 conditional roadmap**,不要在 Stage 3 完成前实现 / 验证 cfg。

**Prerequisite**:Phase 3.5 PASS。

cfg 变化:
```toml
team_size_random = [1, 2, 3]    # 每局 random sample
char_pool = ["v_phase2 7 char list"]  # 双方独立 random sample team_size 个
# 其它继承 stage 3
```

**注意**:multi-char 后元素反应自然 active,**需 v_phase2 lua 至少支持基础反应触发**。Stage 4 时 v_phase2 deferred Batch 1 部分项需先 ship(凯亚-寒冰之棱 / 1 张 trigger 卡 任 1 个反应)。

---

## Phase 3.7 · Stage 5 train(60-100 GPU-h,deferred) · ⏸ PENDING Stage 4 验证

> **⚠ review F.2(2026-05-14)**:Stage 4 未启动前不实现 Stage 5。Stage 5 cfg 当前仅是 placeholder。

**Prerequisite**:Phase 3.6 PASS + v_phase2 deferred Batch 1-2 完整 ship。

cfg 变化:
```toml
card_pool = "v_phase2_full"  # 完整 v_phase2 deck pool
team_size_random = [3]       # 固定 3 char(default GICG)
```

---

## Compute budget tracking

| Phase | 平台 | 预计 GPU-h | 累计 |
|---|---|---|---|
| 3.1 implementation | Mac dev | 0 | 0 |
| 3.2 cross-platform | Windows + Mac | 0 | 0 |
| 3.3 eval 协议 | Mac dev | 0 | 0 |
| 3.4 Mac smoke | Mac CPU | 0 | 0 |
| **3.5 Stage 3 train** | **5070 Ti** | **25-40** | 25-40 |
| 3.5b Stage 3 ablation reserve (review F.4) | 5070 Ti | 24-48 (6-12 GPU-day @ 4-8h/day) | 49-88 |
| 3.6 Stage 4 train | 5070 Ti | 40-60 | 89-148 |
| 3.7 Stage 5 train | 5070 Ti | 60-100 | 149-248 |

Budget 168 GPU-h/week。**Stage 3+4 一周内完成,Stage 5 需 v_phase2 deferred 完成后 follow-up**。

> **review F.4(2026-05-14)**:3.5b ablation reserve = 若 Stage 3 pilot wp_mean 卡在 0.20-0.30 中间区域,按 PLAN 'Paradigm risk audit (review A)' 决策树进入 A.1/A.2/A.6 ablation(单条 1-2 GPU-day,~6 条)。预算从 3.5 主路径 25-40h 之外另留 24-48 GPU-h。3.5b 超支 → 转 closure(per A.4)。

---

## Risk

1. **Logit-as-Q bilinear 表达力不足**:若 Stage 3 卡在 0.30-0.45,可能 bilinear 限制了 Q 表达,需 fallback 到 A2 独立 Q-MLP 路径。
   - **Fallback 触发阈值**(review B.3): pilot 100k frames 上, Mac daemon eval n=128 × 2 sides vs F1-D2 持续 3 次 eval round `wp_mean < 0.30` (CI95 上限 < 0.40) → 触发 A2 fallback (~80-120 LOC: 在 ActorCritic forward path 并联一个独立 Q-MLP head, DMC 只用该 head 训练)。
   - **A2 接口 spec**(review F.5): `training/framework/network/actor_critic.py` 加 optional `q_head_extra: Optional[nn.Module] = None` ctor 参数。forward signature: `q_head_extra(trunk_out, action_emb) -> (B, max_actions) Tensor`。DMC 走该 head 训练 `Q(s, a) ≈ G`,不动 policy_head / value_head / delta_pred_head。预留 hook 不现在代码 stub(B.3 触发时再 implement)。
2. **Opp pool 30% historical 比例失衡**:若实测 historical 太弱拖整体训练 distribution,调整到 20%
3. **Multi-process on Windows native**:spawn 启动慢,首次训练 ~30-60s overhead(steady-state OK)
4. **TCP localhost socket latency**:vs Unix socket 慢 ~5-20μs/req,RL hot loop 内总累积可能影响 throughput < 5%,可接受
5. **v_phase2 Batch 1 lua 落地速度**:Stage 4 prerequisite,需与 Phase 3.6 训练前协调

---

## Paradigm risk audit (review A)

review A 节列了 6 项 paradigm 层质疑 — 不是 bug,而是 "DMC 能否在 GICG 上 work" 的先验性担忧。决策:**不动代码,先跑 100k frames pilot 实测,根据 wp_mean 走势进入下面 ablation 路径**。审计每条原文 → 解释 → ablation 触发条件。

### A.1 Task structure 同构性
DouZero 成功靠开局后无随机性 + card combo 组合先验 + episode ≤ 100 step;GICG 每回合 8 骰 + 双方抽牌 + episode ~340 step。同构性弱。
**Ablation**: pilot 后看 reward variance / loss 振荡。如 train/loss 持续 1.0±0.3 不降 → A1 + A.2 同因。

### A.2 MC return 长 episode + 强随机 → 方差爆炸
γ=1 让一个 episode 内所有 acting 状态共享 ±1。骰子运气 backprop 到 300 个无关状态。
**Ablation**: 加 step-discounted return (γ < 1) 测对照,或加 TD(λ) bootstrap (需 value head, 与 B.2 fallback 合并)。Trigger: pilot loss 不降 + 双方 W/L 不对称。

### A.3 PASS 标准 vs ceiling
Registry 文献 ceiling ~ 0.271 (s068 best AZ asymmetric) / F1-D2 vs F1-D2 control 0.54。PASS ≥ 0.50 = ceiling + 0.23。
**Ablation**: pilot 后实际 wp_mean = X → 更新 PASS 标准为 max(0.30, ceiling - 0.10)。即如果 paradigm-agnostic upper 0.27, DMC ≥ 0.20 = 实际"接近 ceiling"。

### A.4 Closure 未引用
RL 路线 closure (memory_project_rl_routes_closure_2026_05_12) 列了已 closed 集合:DMC 是否属于?需要确认 DMC vs closure root cause (per-step 骰子方差 / multi-char emergence / F1-D2 局部最优陷阱)。
**Ablation**: 如 pilot 失败,论证 DMC 失败属于 closure 已知 root cause 还是新模式 → 决定是否再开新 paradigm。

### A.5 Imperfect-info 评估缺 exploitability
Mac daemon eval 只测 vs F1-D2/F1-D4,不测 exploitability。即使 DMC = 0.50, 可能仍高 exploitable。
**Ablation**: pilot wp_mean 通过 PASS 后,加 vs CFR best-response 1 次 spot-check (用 training/cfr/ 栈生 BR 测 100 局,wp < 0.30 → 高 exploitable)。

### A.6 GICG 缺组合先验
DouZero 在 Doudizhu 上 work 依赖 single/pair/sequence 组合规则,MC 在结构相似状态间共享信号。GICG action 是 dice payment + skill/card index,单 step 状态相似性低。
**Ablation**: 加 action embedding (per-action class) 提高状态相似性。Trigger: pilot loss 降但 wp 不升。

### Pilot 后决策树
1. wp_mean ≥ 0.30 + CI95 上限 ≥ 0.40 → 继续 Stage 3 full train(2e9 frames)
2. 0.15 ≤ wp_mean < 0.30 → 触发 B.3 A2 fallback (独立 Q-MLP)
3. wp_mean < 0.15 → 进入 A.1/A.2/A.6 ablation 路径 (~3-5 GPU-days budget),最后还失败 → DMC 路线 close 转 closure 集合

---

## Phase 3.2 / 3.4.5 / 3.5 implementation tracking(2026-05-18 audit)

> 本节是 audit 结果 + actionable sub-tasks(基于 grep 验证实际 ship 进度,非 design intent — 上面 §Phase 3.x 是原 design plan)。

### Phase 3.2 status(3/3 done)

| Sub-step | 状态 | 证据 |
|---|---|---|
| 3.2.1 `libgicg.dll` Windows build | **DONE** | 2026-05-14 verify(per `reference_windows_gpu_box` memory)|
| 3.2.2 Platform detect adapter | **DONE** | `gicg_env/engine.py:_find_lib` 已 `sys.platform` dispatch |
| 3.2.3 TCP socket replace Unix | **DONE** | `tools/eval/eval_service{,_server}.py` AF_INET(commits 6e8f40c + 18338f5);cross-platform smoke at tools/eval/tests/(0f89583 + 0b3c709)|

#### Phase 3.2 剩余 actionable plan(~半天,~80-120 LOC)

| Task | 说明 | LOC |
|---|---|---|
| **T-3.2a** | PLAN.md §3.2.3 路径校正(2026-05-18 已 done) | ~10 doc |
| **T-3.2b** | `tools/eval/eval_service_server.py`: `AF_UNIX` → `AF_INET` + bind `(host, port)`,读 `GICG_EVAL_PORT`(default 9100)+ `GICG_EVAL_HOST`(default `localhost`)。不留 `AF_UNIX` fallback。 | ✅ ~30 — commit 6e8f40c |
| **T-3.2c** | `tools/eval/eval_service.py` client 同步:`AF_INET` + 读同 env var。 | ✅ ~20 — commit 6e8f40c |
| **T-3.2d** | `tools/eval/tests/test_socket_cross_platform.py`(新):Mac AF_INET localhost smoke + 文档说明 Windows 通过 ssh 跑相同 test verify。 | ✅ ~30 — commits 0f89583 + 0b3c709 |
| **T-3.2e** | 更新 `reference_windows_gpu_box` memory 加 `GICG_EVAL_PORT` env var 注释;PLAN.md 3.2 标 DONE。 | ✅ doc — 本提交 |

**Verify gate**:Mac `pytest gicg_env/tests/ tools/eval/tests/ -q` + Windows ssh `pytest gicg_env/tests/ -q` 全 PASS。

---

### Phase 3.4.5 status(~75% done)

| Sub-step | 状态 | 证据 / 缺口 |
|---|---|---|
| 3.4.5.1 OMP / threading control | **DONE (100%)** | `+ torch.set_num_interop_threads(1)` shipped(commit 259356f);`harden_child_env` 5 env var + `torch.set_num_threads(1)` + `torch.set_num_interop_threads(1)` 完整 |
| 3.4.5.2 CPU affinity | **DONE (actors + learner; eval deferred)** | wired in DMCParadigmConfig + actor_main + run_paradigm_train(commit 9663e0a);eval_service CLI flag deferred to follow-up F-3.4.5b-eval |
| 3.4.5.3 JIT inference | **DONE (infrastructure; DMC runtime NO-OP)** | use_jit_trace wired in LocalNetworkProvider + InferenceServer + _server_loop(commits 2a896f8 + ac7821d);DMC trace path NO-OP because DMCNetwork.forward raises NotImplementedError;provider_factory plumbing gap acknowledged in field comment(see F-3.4.5c-factory follow-up)|
| 3.4.5.4 Shared mem replay | **DONE** | `training/core/actor/{weights_shm.py, ipc/ring.py}` `multiprocessing.shared_memory` ring buffer |
| 3.4.5.5 Engine call minimize | **N/A** | 无 redundant call,plan 不要求 fix |
| 3.4.5.6 cProfile 验证 | **DONE (Mac baseline); PENDING (Windows)** | `tools/dmc/profile_actor.py` + Mac 274 fps captured(commits c26b0bb + e2c414e);Windows X3D run blocked by box availability |
| 3.4.5.7 Throughput baseline | **PARTIAL (Mac baseline; Windows pending)** | Mac M-series baseline 274 fps in notes.md;X3D ≥ 1200 fps target requires Windows box access |

#### Phase 3.4.5 剩余 actionable plan(~1-2 day,~200-300 LOC + Windows-side profile run)

| Task | 说明 | LOC |
|---|---|---|
| **T-3.4.5a** | `_mp_helpers.harden_child_env` 加 `torch.set_num_interop_threads(1)` trivial fix。 | ✅ ~1 — commit 259356f |
| **T-3.4.5b** | Wire `cpu_affinity_*`(死字段 → 真用):actor process boot 调 `psutil.Process().cpu_affinity(cfg.cpu_affinity_actors)`;learner / eval 同样 wire。default X3D:actors `[0..7, 16..23]` / learner `[8]` / eval `[9..15]`。Mac / Linux fallback:skip if no CCD assumption。 | ✅ ~40 — commit 9663e0a(actors + learner only;eval deferred — see F-3.4.5b-eval)|
| **T-3.4.5c** | Wire `use_jit_trace`(死字段 → 真用):actor 启动后 `trace_once(net, example_obs)`,hot loop `traced_net(*obs_args)`(已有 `inference_mode`);`cfg.use_jit_trace=True` 才走 traced 路径。 | ✅ ~60 — commit 2a896f8(infrastructure wired;DMC NO-OP per field comment;see F-3.4.5c-test for server_loop test coverage)|
| **T-3.4.5d** | `tools/dmc/profile_actor.py`(新):single-actor 5min smoke + cProfile output `actor.prof` + snakeviz HTML。Mac + Windows 都可跑(Windows 是 baseline 真测点)。 | ✅ ~60 — commits c26b0bb + e2c414e(Mac baseline 274 fps captured;Windows follow-up in T-3.4.5e)|
| **T-3.4.5e** | Windows X3D profile run:ssh + 跑 `profile_actor.py` 5min,记 per-actor fps + cProfile top hotspots → `notes.md "## Phase 3.4.5 — CPU profile results"`(目前空)。target verify per-actor ≥ 1200 fps。 | run + doc(PENDING — Windows-blocked)|
| **T-3.4.5f** | Multi-actor smoke total throughput(Windows):24 actor smoke 5min,记 total fps ≥ 28k → `notes.md` "Phase 3.4.5 verdict"。若 < target → cycle(profile → 优化 → retry)。 | run + doc(PENDING — Windows-blocked)|
| **T-3.4.5g** | Phase 3.4.5 close 决策:PASS(per-actor ≥ 1200 + total ≥ 28k)→ close + 准备进 Stage 3 train;FAIL → 扩 ablation cycle。 | doc(PENDING — Windows-blocked)|

#### Phase 3.4.5 follow-ups discovered during ship

| Task | 说明 | LOC | 触发 |
|---|---|---|---|
| **F-3.4.5b-eval** | `tools/eval/eval_service.py` 加 `--cpu-affinity` CLI flag(可选 env `GICG_EVAL_CPU_AFFINITY`)。`DMCParadigmConfig.cpu_affinity_eval` 是 documentation 字段,ops 启动 eval_service 时手动传给 `--cpu-affinity`。 | ✅ ~30 | Task 3 spec deferred(eval_service 是 separate process,DMC cfg 无法 runtime 触达) |
| **F-3.4.5c-test** | `training/tests/test_inference_server_jit_trace.py`(新):mp Process spawn smoke,verify `use_jit_trace=True` ctor flag → `_server_loop` 实际 trace + `'weights'` msg 触发 invalidation。 | ✅ ~50 | Task 4 review:`_server_loop` `use_jit_trace=True` path 零测试覆盖,只 LocalNetworkProvider 测了 |
| **F-3.4.5c-factory** | `training/core/actor/provider_factory.build_network_provider` 扩展 `use_jit_trace` 参数,要求 `InferenceCfg` 加第 5 字段或别路径绕过 R7 4-字段契约。OR document that paradigms wanting trace 必须 bypass factory(现状)。**Decision (2026-05-18)**: Option B documented; paradigm-side `mp_provider_path` factory bypasses `build_network_provider` to activate trace. `InferenceCfg` R7 4-field contract preserved. | ✅ ~25 doc-only | Task 4 review:wiring 链 inert at factory site;DMC NO-OP 之外还有 generic gap |

**Verify gate**:per-actor ≥ 1200 fps + total ≥ 28k fps(24 actor on X3D)。

---

### mp 统一架构 backlog(2026-05-19 audit + Windows benchmark 触发)

> 触发:2026-05-18 Windows 24-actor benchmark(shell-spawn 独立 process)实测 1484-1705 fps,vs PLAN.md §3.4.5.7 target 28k → **gap ~17×**。Mac 264 fps + Windows 152 fps single-actor 共同确认 collector CPU 推理是真瓶颈,**GPU collector inference 是唯一能闭 wall budget 的路径**。审计发现 mp 模式架构在 repo 内全 paradigm dead:`mp_provider_path` 等字段 resolver 转发到 user-supplied 路径,但 **0 cfg 设值,0 paradigm 提供真实 factory 实现**。
>
> 2026-05-19:P2-PoC 首次 dispatch 实施 78 min 后 subagent API 403 失败,改动 scope 超出原 spec(动 `episode_runner.py` + `ipc/ring.py` + 新建未授权 `_mp_internal.py`),未 commit。原因:**真正的 mp 统一架构是跨 paradigm core change,scope 在单次 subagent dispatch 内难以稳定收敛**。

#### 子任务拆解(P2-PoC 拆为 5 子项)

| 子任务 | 内容 | LOC | 跨 paradigm 风险 |
|---|---|---|---|
| **MP-1** core/actor.actor_main 加 `inference_client` kwarg | actor_process.py:104 `build_provider(cfg, actor_id)` → 条件性附带 `inference_client` kwarg(non-None 时);其他 paradigm 旧 factory 签名兼容(不接 kwarg 不破) | ~15 | 中:AZ/PPO/CFR/BC mp factories 全做 backward compat regression |
| **MP-2** DMC mp_factories.py 实装(3 factory) | `build_dmc_env_factory` / `build_dmc_opp_registry`(限 random opp,greedy/historical 需 weights sharing 另说) / `build_dmc_provider`(返 RemoteNetworkProvider) | ~100 | 低:DMC-only,新文件 |
| **MP-3** DMCMultiProcessCollector._bootstrap GPU server 装配 | 父进程构 `DMCInferenceNet → InferenceServer(device='cuda', max_batch=N) → N × InferenceClient.attach → server.start → 每 actor 自带 client via per-actor kwargs` + `close` hook | ~80 | 低:DMC-only,但 mp.Queue cross-spawn pickle 路径需测 |
| **MP-4** configs/dmc/gpu_async.toml + mp smoke test | extends smoke.toml,async mode,num_actors=2,device=cpu(Mac 验)/cuda(Win 验);test 验证 transition 流过 ring | ~60 | 低 |
| **MP-5** InferenceServer 真 batching | `_server_loop` 收 N requests → stack obs_dict per-key → 1 forward → scatter response;dict obs 变长 hook field 需 batch-max padding | ~150 | 高:架构改 InferenceServer,影响所有 server 用户(AZ 已有);需 paradigm-aware stacking helper |

#### 顺序建议

```
MP-1 → MP-2 → MP-3 → MP-4(Mac 验)→ Windows MP-4(GPU 验)→ MP-5(batching 优化)
```

- MP-1~4 是 PoC,可分 4 独立 commit subagent-driven 串行 ship,每步 100 LOC 以内
- MP-5 真 batching 是 perf 优化,先 PoC 通(单 actor → 1 server,无 batching)再做
- Mac CPU 验 architecture 通即 ship MP-1~4;Windows GPU benchmark 在 P3 一并跑

#### Risk register

- **R1 跨 paradigm regression**:MP-1 改 core/actor 影响 AZ/PPO/CFR/BC,每 dispatch 需跑全 paradigm smoke regression
- **R2 mp.Queue pickle invariants**:InferenceClient 跨 spawn 时 mp.Queue 必须 picklable,且 response queue 不被父进程 GC
- **R3 weight sync window**:WeightsSHM + 共享 InferenceServer 两条 weight 同步路径,需明确"InferenceServer 自己拉 weights 还是父进程 publish"(决策点)
- **R4 single actor on GPU 比 CPU 慢**:cross-process IPC overhead;只在 N ≥ 4 actor batch 时才 win,smoke 单 actor 数据可能误导
- **R5 InferenceServer batching dict obs**:DMC obs 15 tensor 含变长 hook 字段,padding 策略需 paradigm-aware,不是通用框架能解的

#### 当前 stash(2026-05-19 partial work)

未 commit 的文件(下次 implementer 决定 cherry-pick 哪些):
- `training/paradigms/dmc/mp_factories.py`(spec 内,155 LOC)
- `training/paradigms/dmc/_mp_internal.py`(scope creep,75 LOC — 跳过)
- `configs/dmc/gpu_async.toml`(spec 内,29 LOC)
- `training/tests/test_dmc_mp_factories.py`(spec 内,72 LOC)
- modified `actor_process.py` / `collector.py` / `config.py`(spec 内但 scope 超)
- modified `episode_runner.py` / `ipc/ring.py` / `test_dmc_async_collector.py`(scope creep,跳过)

下次 dispatch 建议:**tighter scope per subagent**(MP-1 / MP-2 / MP-3 / MP-4 分开,每个 ≤ 100 LOC),避免单次 78 min 大 dispatch 风险。

---

### Phase 3.5 / compile / NaN backlog(2026-05-19 pilot 触发)

> 触发:Stage 3 pilot 跑 12342 train_steps 后 grad_norm=inf NaN;T9 Mac compile benchmark 揭示 cold-start 5-10s 不适合 smoke fast-path;train_step 路径 compile 未覆盖。

#### B-win-wire-fix(2026-05-26 ship,FIXED)

> 触发:I29 R7.2 squash 到 main 后跑 stage3_b_v_legacy_go.toml on Win 卡死 5+ min,master 看似 hang。

**Root cause(经 6 层 diagnostic 定位)**:

1. `DMCParadigm._make_go_collector` 把 raw `DMCNetwork` 直接传给 `DMCGoSubprocessCollector` → `InferenceServer` host 该 network。
2. InfServer 收到 Go actor inference request 时调 `network(obs, mask)` (即 `DMCNetwork.forward`) → `DMCNetwork.forward` raise NotImplementedError (training-only,生产应该走 `forward_batch` 或 `select_action`)。
3. Go actor 第 1 个 inference request 报 server error → `runEpisode` err → Go actor goroutine exit → `runWg.Wait()` return → `Run` return nil → main exit rc=0 (silently)。
4. Master 端 `subprocess.Popen` 的 `stderr=PIPE` **无 reader thread drain** → Go 的 fail-loud stderr 被 OS pipe buffer 吞,master 看似 hang (实际等不到永远不来的 episode transitions)。

**Fix(2 commits)**:

- `training/paradigms/dmc/paradigm.py`(核心 fix): `_make_go_collector` 把 `network.net` (ActorCritic underlay) wrap 进 `DMCInferenceNet`,再传 collector。 与 `perf_smoke` test fixture (`_build_dmc_inference_net`) 同模式。
- `training/core/actor/go_subprocess.py`(强化 fix): 加 stderr drain background thread,从此 Go binary 任何 fail-loud error 都能 surface 到 master 的 `RuntimeError`(类比已有的 stdout reader thread)。 之前 stderr unread → 错误隐形 → master 卡死 looks like hang。

**验证**:
- cpu+N=1+10k frames probe on Win box: Go binary alive,跑了 3+ episodes (`runEpisode done OK`),pipeline 工作。
- production cuda+N=19+100k frames pilot 跑前 30s 反复挂同样 root cause(stderr-drain fix 后能 surface 真 error,paradigm.py fix 后 inference 通)。 完整 100k pilot 待 Win box 可用时验证。

**Implication for Stage 3 production**:Stage 3 Windows GPU full train (Phase 3.5 Step 5) 用 `stage3_b_v_legacy_go.toml` 现可 spawn 通,**B-nan-pilot 仍是 train-阶段 blocker(此 fix 仅解 spawn-阶段)**。 下一轮 Win box 可用时跑 100k pilot,过得了 train_step 12342 (NaN trigger 历史点) 才算 B-nan-pilot ACCEPTANCE。

#### B-go-sustained-collection-deadlock(2026-05-27 in-flight)

> 触发:R7.2 spawn-wire fix 后 100k production pilot on Win box (cuda + N=19) 跑 25 min 后 frames 卡 5862(34 episodes),后续 iter wall 60.5s × 24 iter 仅 +1 episode。 actors / master / InfServer 都 alive,GPU 7% util — 整个 pipeline deadlocked but 不 fail-loud。

**已 ship 的 3 层缓解** (`feature/dmc-phase35-stage3` 分支):

1. **Architectural fix — `TransitionWriterShm.Push` blocking retry**(`gicg_actor/transition_writer_shm.go`):ring full 时 spin retry 1ms backoff,bounded 30s timeout 后 fail-loud(替代历史 "drop on full 然后 paradigm.go 直接 return nil" — 违反 [[python_arch_mimicry_for_go_port]],等价于 Python mp.Queue.put() default blocking)。 加 atomic `pushTotal` / `pushWaitTotalNs` / `pushDropTimeout` 计数 + `Stats()` getter。
2. **Backpressure metric infrastructure**:
   - Go side(`gicg_actor/dmc/paradigm.go` runActor 内):每 50 episode emit `[gicg_actor backpressure] actor=N ep=K push_total=T push_wait_ms=W push_drops=D` 到 stderr。
   - Python side(`training/core/actor/go_subprocess.py` `_drain_stderr` 内联 regex parse + per-actor `_bp_stats` snapshot + `get_backpressure_stats()` getter):master 端 stderr_thr drain + parse → 暴露给 collector。
   - Collector(`training/paradigms/dmc/go_subprocess_collector.py` `_aggregate_backpressure_metrics`):聚合各 actor push_total / push_wait_ms / push_drops + 计算 push_wait_ms_avg → emit `'backpressure'` kind 进 `metrics.jsonl`(通过新加的 `attach_metrics_logger` hook)。
3. **Capacity 适度提**(`training/core/actor/pipeline_tuning_cfg.py` 默认 `shm_capacity` 8 → 32):给 train cycle burst headroom 减少 push_wait_ns 触发频率;但 correctness 不依赖 capacity(blocking 保证 no drop)。

**额外 diagnostic counters**(ship 给下次 session debug 直接用):
- Assembler(`_go_assembler.py`):`n_ingest_called` / `n_assembled` / `n_dropped_static_miss` / `n_evicted_inflight` 累计;`stats()` 暴露。
- Collector loop(`go_subprocess_collector.py`):`collect_pops_empty` / `collect_pops_got` / `collect_decode_err` / `collect_n_ready_drained` per-call;`shm_ring_peek_count`(直读 SHM header `count` atomic int)— 关键!查跨进程 view 是否一致。

**当前 pilot 数据 vs 期望**(metric reveal 出真问题):
- iter wall delta = **60.5s** = `collect_deadline_s` 每次 hit
- `collect_pops_empty: 11194`(60s × 5ms poll = 12k 与之吻合)+ `collect_pops_got: 0` — **master 端 ring 持续空 60s**
- `assembler_n_assembled: 35` 在 steady-state 持续不增 — 没 episode 到 master
- GPU 7% util — InfServer 空闲,inf request 流量低 → actors 没在跑 me-step

**待 debug(下次 session 首要)**:
- 关键 unknown:`shm_ring_peek_count` 当 collect_pops_empty 时是不是真 0?如果 > 0 则 **跨进程 SHM counter sync bug**(actor push 后 count++,master pop 读不到 item — race?Win shm_win.c atomic 模型 vs POSIX 差异?);如果 = 0 则 **actors 在 push 之前的某步卡**(inf request? minimax?)。 下次 session pilot 100k 跑起来后第一时间 grep `shm_ring_peek_count` 值。
- 若 ring count > 0 但 pop None:检查 `shm_win.c` 的 `shm_ring_pop` 与 `shm_ring_push` 之间的 head/tail/count `__atomic_*` 内存顺序(possibly 需 `__ATOMIC_SEQ_CST` 而非现 `__ATOMIC_ACQUIRE/RELEASE`)。
- 若 ring count = 0:加 InfServer queue depth + inf request latency metric,看 actors 是否 inf 阻塞。
- B-nan-pilot 仍是上游 blocker;此 deadlock fix 后才能验证 train_step 12342 NaN 是否还在。

| 子任务 | 内容 | LOC | 触发证据 |
|---|---|---|---|
| **B-compile-smoke** | **不要** 在 `smoke.toml` 加 `inference_acceleration='compile'`。理由:torch.compile cold-start ~5-10s,smoke 设计是 < 1s fast sanity per CLAUDE.md。T9 Mac d_model=32 smoke 60s wall:compile=69.9 fps vs none=270 fps(60s 中大半是 cold-start overhead)。**production cfg(default.toml / stage3_pilot.toml)是 compile 收益场,smoke 维持 none**。doc-only(record decision)| 0 | T9 实测;CLAUDE.md `smoke` marker 设计意图 |
| **B-compile-train** | train_step path(forward+backward+optimizer)未被 P1 `inference_acceleration` 覆盖。`pipeline.py:124-139` 直接 `loss_fn.compute(network, batch)` + `loss.backward()`,无 compile wrap。per profile_train Mac:**backward 58.6% + train forward 38.3% = 97% wall** — train compile 才是真大头。实装:`paradigm.make_network` 后如 cfg 有 `train_acceleration='compile'` 则 `network = torch.compile(network, dynamic=True)`。`dynamic=True` 必须(buffer.sample 不同 batch_size 触发 recompile cache thrash)。 | ~30 | profile_train Mac d_model=32 baseline:transformer encoder forward 37% + multi_head_attn 33% + backward 58.6% |
| **B-nan-pilot** | Stage 3 serial pilot 用 lr=5e-5 + max_grad_norm=1.0 仍在 step 12342 撞 grad_norm=inf。`clip_grad_norm` 在 raw grad 算完后才 firing,raw 已 inf 时 clip 无用(divide by inf → 0/nan grads,但 nan_guard 看 raw)。修法选项:(a) lr 再降 1e-5,(b) DMC loss 数值稳定性 audit(logit-as-Q + MSE 在 ±1 G 上可能溢出),(c) gradient inf 检测 + skip step 而非 crash。**Stage 3 production 前必修**。 | ~10-30 取决方案 | nan_dump_12342 in `artifacts/202605190105_000029_dmc_stage3_pilot/` Win box |
| **B-mp-transition-type** | mp 模式 actor 走 EpisodeRunner 产 `core.Transition` (frozen) 但 `DmcReplayBuffer.push_episode` `t.G = G` 需 mutable(DmcTransition 非 frozen)→ FrozenInstanceError。re-sync Win 后 serial 路径不撞(serial 走 play_one_episode 产 DmcTransition);**mp 端到端训练仍受影响**。修法:在 mp collector 出口将 EpisodeRecord.transitions 转 DmcTransition(需 obs_dict 重建 — 复杂),OR `push_episode` 用 `dataclasses.replace` 而非 in-place,OR 重写 mp 路径让 actor 直接产 DmcTransition。 | ~50-150 | P2-PoC stash 内 + 04:50 Stage 3 mp pilot Win 重现;mp 端到端 train 全链未通 |

#### 优先级建议

- **B-nan-pilot 最 urgent** — Stage 3 production train 阻塞;先修 grad 处理
- B-compile-train 是真 perf 大头 — train 通后做,可与 mp 端到端独立 ship
- B-mp-transition-type 是 mp 模式 unblock — 现 serial 模式已通 Stage 3 production(只是慢),mp 改进延后
- B-compile-smoke 是 doc-only,本节本身即是 record

---

### Phase 3.5 Stage 3 启动 checklist

#### Step 0 — Prereq verify(两者全 PASS 才进 Step 1)
- [ ] Phase 3.2 ship 完成(T-3.2b/c/d 全 done,verify gate PASS)
- [ ] Phase 3.4.5 ship 完成(T-3.4.5a..f 全 done,verify gate PASS)
- [ ] Windows GPU box reachable:`ssh dev@192.168.31.56 'powershell -Command Get-Date'` 通

#### Step 1 — Code bundle Mac → Windows
```bash
# per reference_windows_gpu_box memory
cd ~/Projects/gicg_mono
tar -czf - --exclude=artifacts --exclude=.venv --exclude=ref --exclude=__pycache__ \
  --exclude='.git' --exclude='*.pyc' --exclude='gicg_env/libgicg.dylib' \
  --exclude='gicg_env/libgicg.h' . | \
  ssh dev@192.168.31.56 'powershell -Command "cd D:\gicg_dev; tar -xzf -"'

ssh dev@192.168.31.56 'powershell -Command "Get-ChildItem D:\gicg_dev -Recurse -Force | Where-Object {\$_.Name -like \"._*\" -or \$_.Name -eq \".DS_Store\"} | Remove-Item -Force"'
```

#### Step 2 — Windows build verify
- [ ] `libgicg.dll` build(`Test-Path D:\gicg_dev\gicg_env\libgicg.dll`)
- [ ] venv install + cuda forward verify(`torch.cuda.is_available()` + matmul sm_120)

#### Step 3 — Pilot run(100k frames,~10-30 min)
```powershell
cd D:\gicg_dev
$env:OMP_NUM_THREADS = "1"; $env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -X utf8 -m tools.runs.train configs\dmc\stage3.toml `
    --override paradigm.dmc.total_frames=100000
```

监控 `metrics.jsonl`,出 3+ eval round 后看 `wp_mean`。

#### Step 4 — Pilot decision tree(per §Paradigm risk audit / Pilot 后决策树)

| pilot wp_mean(3 eval round vs F1-D2 n=128×2 swap) | 行动 |
|---|---|
| **≥ 0.30 + CI95 上限 ≥ 0.40** | → Step 5 full Stage 3 train |
| **0.15 ≤ wp < 0.30** | → 触发 B.3 A2 fallback(独立 Q-MLP head ~80-120 LOC)+ pilot 重跑 |
| **< 0.15** | → A.1/A.2/A.6 ablation(γ<1 / step-discount / action embedding,~3-5 GPU-days);全 fail → DMC paradigm **close** 进 closure 集合 |

#### Step 5 — Full Stage 3 train(2e9 frames,~16-25h wall)
```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.runs.train configs\dmc\stage3.toml
```

**早停**:
- vs F1-D2 WP 持续 3 次 eval > 0.50 + F1-D4 不 collapse(> 0.30)→ 早停 PASS
- 16h 内 < 0.30 → early abort + investigate

#### Step 6 — Verdict + 落 doc
- **PASS(WP ≥ 0.50)**:`tools.runs.mark <NNN> --status done` + 落 ADR `paradigm-dmc` capability spec(走 openspec change)
- **partial(0.27 ≤ WP < 0.50)**:user 决策 — A.3 修正 PASS 阈值 / 切 stage / 加 lever / 转 ablation
- **FAIL(WP < 0.27)**:`mark --status done --notes 'closure'` + 落 closure ADR(加 ADR-0009/0010 集合);BC ckpt 仍作 production fallback

---

### Task dispatch 顺序(综合)

| 优先级 | Task | 估时 | 阻塞 |
|---|---|---|---|
| 1 | T-3.2b..e(TCP socket migration) | ~半天 | 阻塞 T-3.4.5e/f(Windows multi-actor 需 eval socket 通)|
| 2 | T-3.4.5a..d(local infra wiring) | ~半天 | independent,可与 T-3.2 并行 |
| 3 | T-3.4.5e..g(Windows X3D profile + verdict) | ~1 天(real Windows 跑)| depends on T-3.2 + T-3.4.5a..d |
| 4 | Phase 3.5 Step 0-6(per 上方 checklist) | ~1-2 天(若 pilot PASS) | depends on T-3.2 + T-3.4.5 全 done |

**总估**:3-5 天到 Phase 3.5 pilot 决策点。
