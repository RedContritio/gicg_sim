# I29 Go-actor pool 完整状态 dump — 2026-05-24 EOD

完全重设计前的现状归档。 包含所有 branch / 实测数据 / root cause / 失败教训 / 重设计 constraints。

## 目录
1. [Goal 回顾](#goal)
2. [Branch 拓扑](#branches)
3. [完整 bench 数据](#bench)
4. [Per-stage timings](#timings)
5. [3 架构对比](#archs)
6. [Root cause 分析(已 verify vs hypothesis)](#rcause)
7. [Instrumentation gaps](#gaps)
8. [尝试 + 失败原因](#tried)
9. [完全重设计 constraints](#redesign)
10. [Open questions / 待验](#open)

---

<a name="goal"></a>
## 1. Goal 回顾

User session goal (2026-05-24):
> 充分优化 go runtime 当前实现,使 go 方案性能**显著优于** python 多进程版本,且**接近理论性能极限**。 所有与理论极限不相符的部分都需要有**可信解释**。 Mac+Win 都至少不低于 python。 多设计少运行 + 多用 subagent-driven-development。

**Status**: ❌ Goal NOT met。 Win Go-actor 在所有 path 都 < Python mp;Mac 由于 variance 不能严格比较。

---

<a name="branches"></a>
## 2. Branch 拓扑

```
main (pre-session base)
└── feature/i29-go-actor-pool        ← Phase A + T-B1 done
    │   Commits: 9f6ab7e..20f8843 (Phase A 5 task + T-B1 + bench tooling + Mac fair bench)
    │   bench: Mac N=4 (T-C1) + Win N=16 (T-C2 pre-F1)
    │   verdict: Go TCP < Python mp (Mac 3.8x, Win 1.5x)
    │
    ├── feature/i29-go-actor-episode-push   ← F1 done
    │   Commits: f1b6a29..4dd6427 (F1 episode-granularity push + Win F1 bench)
    │   bench: Win N=16 26.15 fps (vs pre-F1 26.9) — fps 未动
    │   verdict: F1 push fix 正确实现 (push 434ms→2.24ms, 13x fewer pushes) 但 fps 未改善
    │
    └── feature/i29-go-actor-shminf          ← Path A SHM done
        Commits: cbc9ea6..c72c8ec (Phase 1-4 SHMRing + Win SHM bench + cfg wiring)
        bench: Win N=16 22.68 fps — Win Path A FAIL (比 TCP 还慢 13%)
        verdict: ShmBridge GIL contention master process = root cause
```

3 branch 各自独立 ship,**每个都从对应基线起,均未 merge**。 main 干净未改。

---

<a name="bench"></a>
## 3. 完整 bench 数据

### Win N=16 (5070 Ti + 9950X3D, hostname DESKTOP-GHJCC7Q, cfg stage3_b_v_legacy)

| Run | Backend | Branch | fps | eps/s | mem RSS | inf RTT |
|---|---|---|---:|---:|---:|---:|
| Python mp baseline | mp.Process pool | (any) | **40.14** | 1.845 | 3.8 GB | ~? (gap) |
| Go-actor TCP pre-F1 | TCP socket | i29-go-actor-pool@9ba6311 | 26.90 | 1.901 | 4.7 GB | 64 ms |
| Go-actor TCP F1 | TCP + batch push | i29-go-actor-episode-push | 26.15 | 1.835 | 9.7 GB | 64 ms |
| **Go-actor SHM** | SHMRing inference | i29-go-actor-shminf | **22.68** | 1.667 | 10.5 GB | 69 ms |

**关键观察**:
- 3 Go variants 都 < Python mp,gap 30-45%
- F1 没改 fps (transition path 不是 bottleneck)
- SHM 比 TCP **还慢** (master process GIL contention)
- mem 全部 > Python mp,F1+ 翻倍

### Mac N=4 (arm64, d_model=128, pure collector smoke 15s window)

Stage3-shape (赤蝶 vs 墨客, v_legacy pool, full opp_mix), 多 run 实测:

| Backend | n runs | fps/actor range | mean |
|---|---:|---:|---:|
| Python mp | 3 | 34.27-55.26 | **48.1** |
| Go-actor TCP pre-F1 | 3 | 3.82-12.20 | ~7.8 |
| Go-actor TCP F1 | 4 | 6.35-15.85 | ~12.5 |
| Go-actor TCP fresh | 3 | 5.65-14.66 | 9.5 |
| Go-actor SHM | 8 | 1.67-18.42 | 7.7 |

**关键观察**:
- Mac variance huge (3-4x within same config) — single-run perf claim 不可靠
- Python mp 比 任何 Go path 快 4-6x on Mac
- SHM vs TCP on Mac:within variance,无显著差异

---

<a name="timings"></a>
## 4. Per-stage timings (Win N=16,完整 sub-span instrumentation)

### Go-actor TCP F1 (post-T-A1+T-A2+T-A3+T-B1+F1)

```
transition_writer.mutex_wait      n=2520    mean=0.000 ms  ← T-B1 fix 验证
transition_writer.encode           n=2520    mean=0.360 ms
transition_writer.push             n=2520    mean=3234 ms   ← 但 push count 13x fewer
transition_writer.socket_write     n=2520    mean=3234 ms   ← (per episode batch wait drain)

inference_client.encode            n=45000   mean=0.057 ms
inference_client.send              n=45000   mean=0.505 ms
inference_client.recv              n=45000   mean=64 ms     ← inference wait dominant
inference_client.decode            n=45000   mean=0.021 ms
inference_client.request           n=34000   mean=65 ms

dmc.opp_f1d2_select               n=12361   mean=12 ms
dmc.opp_f1d4_select               n=6699    mean=280 ms    ← opp f1d4 expensive
dmc.opp_minimax_select            n=19060   mean=106 ms

dmc.engine_step                   n=71658   mean=0.05 ms
dmc.episode                        n=2450    mean=8181 ms   ← 整 episode ~8s
```

### Go-actor SHM (Path A,master GIL contention)

```
transition_writer.push             n=978     mean=2.5 ms    ← F1 sale push fast OK
inference_client.recv              n=18475   mean=69 ms     ← +5ms vs TCP (worse!)
inference_client.send              n=18450   mean=0.056 ms  ← 9x faster than TCP (好处)
```

Net: SHM 减 send 0.5ms 但 加 recv 5ms = -4.5 ms/call worse。

### Python perf (driver thread)

```
assembler.ingest_episode          (F1)       n=7018    mean=1.302 ms  ← episode path 快
assembler.decode_payload                     n=107133  mean=0.037 ms
assembler.append_buffer                      n=57124   mean=0.078 ms
assembler.try_assemble                       n=7042    mean=0.321 ms

pipeline.loss_compute             n=42084    mean=49 ms     ← 训练 GPU forward 占大头
pipeline.backward                 n=42084    mean=10.6 ms
pipeline.optim_step               n=42084    mean=3.3 ms
pipeline.buffer_sample            n=42084    mean=4.2 ms
pipeline.collect                  n=15416    mean=2.1 ms
```

driver wall: loss_compute 49ms × ~8/s = 392 ms/s (39% wall hold GIL)。

### InfServer (Python mp baseline only)

```
batching_efficiency               mean=0.888           ← 优秀
batch_size_avg                    mean=14.2 (max=16)   ← 接近满载
fillwait_ms_avg                   2.38 ms
forward_ms_avg                    12.56 ms
decode_ms_avg                     47.31 ms             ← decode 主导 process_ms
process_ms_avg                    63.31 ms
requests_per_sec                  208
```

**Go-actor path 的 InfServer stats 全部为空** (instrumentation gap — 见 §7)。

---

<a name="archs"></a>
## 5. 3 架构对比

### Python mp(40 fps baseline)

```
┌─────────────────┐
│ Master process  │
│ - driver loop   │ ← 训练 + collect SHMRing.try_pop (轻活)
│   loss_compute  │
└─────────────────┘
        ↑ SHMRing pickle blob (1/episode, 168KB)
        │
┌─────────────────┐        ┌─────────────────┐
│ Actor[i] proc   │ ──→ mp.Q ──→ │ InfServer proc │
│ (Python)        │ ←── mp.Q ←── │ batched forward │
│  game loop      │              │  + socket_listener │
│  Inf.request    │              │   (本 InfServer proc 内) │
│  ep push to ring│              └─────────────────┘
└─────────────────┘
N=16 instances              Single GPU subprocess
```

**关键**: actor subprocess + InfServer subprocess 之间走 mp.Queue (POSIX shm pipe in subprocess)。 **master process 完全不参与 IPC**,只 train + buffer.push。

### Go-actor TCP (F1 ship)

```
┌────────────────────────────────────────┐
│ Master process (Python)                │
│ - driver loop (GIL hog 37%)             │  ← loss_compute 49ms × 8/s
│ - transition_sink_listener thread       │  ← Go push → master listener
│ - per-actor handler threads (16)        │  ← decode + enqueue
│ - _drain_queue_assemble (driver)        │  ← assembler.ingest_episode
│ - cgo: Go runtime + N=16 goroutines     │  ← actor 跑在 master process 内!
└────────────────────────────────────────┘
        ↑ TCP socket transition (1/episode F1, 168KB)
        │
┌────────────────┐         ┌─────────────────┐
│ Goroutine[i]    │ ──TCP──→ │ InfServer proc  │
│ (Go runtime,   │ ←─TCP─── │ socket_listener │
│  no Python GIL) │           │ + forward_loop  │
│  game loop      │           └─────────────────┘
│  inference req  │
└────────────────┘
N=16 in master process       Single GPU subprocess
```

**关键**:
- Go goroutine 跑 master process 内 (cgo loaded lib) — **不持 GIL** (Go runtime native code)
- transition push 走 TCP → master listener thread (Python) → needs GIL
- master process listener + assembler.ingest + driver loop 都 contending GIL
- inference path goroutine → InfServer subprocess 不经 master — **OK,无 GIL contention**

### Go-actor SHM (Path A failed)

```
┌────────────────────────────────────────┐
│ Master process                          │
│ - driver loop (GIL hog 37%)             │
│ - transition_sink_listener thread       │
│ - InferenceShmBridge thread (Path A 新加!)│  ← drain shm → request_q + drain response_q → shm
│ - assembler.ingest in driver            │
│ - cgo Go goroutines                     │
└────────────────────────────────────────┘
        ↑ TCP transition + ↑ SHM inference req/resp
        │
┌────────────────┐  shm req  ┌─────────────────┐
│ Goroutine[i]    │ ──ring──→ │ InfServer proc  │
│                 │ ←ring──   │ request_q       │ ← bridge push to request_q
│                 │           │ batched forward │
└────────────────┘           └─────────────────┘
```

**关键 fail**: ShmBridge thread 在 master process,从 shm ring drain 后 push 到 request_q (mp.Queue cross-process) 需要 master GIL。 driver 训练时 GIL hog,bridge starve → InfServer 喂不饱 → 吞吐降。

---

<a name="rcause"></a>
## 6. Root cause 分析

### 已 verify (高置信)

1. **T-B1 mutex_wait fix 工作** — Win 实测 mutex_wait 0.000 ms (verified)
2. **F1 push count 减 13x** — Win 实测 33857 → 2520 push (verified)
3. **F1 不改 fps** — Win 实测 26.9 → 26.15 fps (verified)
4. **SHM 不改 inference RTT** — Win 实测 64ms → 69ms (verified,SHM 反而 +5ms!)
5. **InferenceShmBridge 跑 master process** — code inspection (verified at `inference_server.py:427`)

### Hypothesis (待精确测量验证)

1. **Master process GIL contention 是 Go-actor 慢于 Python mp 的主因** — 高置信但缺 timing 数据
2. **TCP localhost vs mp.Queue per-call latency 差 1-3 ms** — 推测,未实测 Python mp 端 inference RTT
3. **assembler.ingest 在 driver thread 与 loss_compute GIL 竞争** — 推测
4. **transition_sink_listener handler N=16 threads GIL contention** — 推测

---

<a name="gaps"></a>
## 7. Instrumentation gaps

### CRITICAL (必须补,否则无法 close hypothesis)

1. **Python mp 端 per-call inference RTT** — 完全无数据
   - 只有 InfServer batching stats (batch_size_avg, fillwait_ms),没 client-side wait time
   - 影响:无法对比 "Python mp 的 inference RTT 是 X,Go-actor TCP 是 Y" — Y 已有 (64ms),X 未知

2. **Go-actor SHM 端 InfServer batching stats** — 实测 metrics.jsonl 无 inf_server kind row
   - 原因:Phase 3 bridge 没 wire `stats_q` 到 master logger
   - 影响:不知 SHM mode 下 InfServer batch_size_avg 是不是变小了

3. **Master process GIL contention time** — 无数据
   - 想知:bridge thread / listener / driver 各自 GIL wait time
   - 影响:无法量化 "GIL contention 损失 X ms"

### IMPORTANT (可助诊断,非阻塞)

4. **Per-actor inference RTT distribution** — 有 mean,无 p50/p95/p99
5. **TCP socket kernel queue depth / retransmits** — 无 (Win+localhost 应该 0,但未测)
6. **Goroutine scheduling latency** — Go runtime 内部数据未 expose
7. **CGo call overhead** — Go ↔ Python boundary cost 未测

### LOW (锦上添花)

8. **GPU pipeline utilization per request** — nvprof 级别,工程化困难

---

<a name="tried"></a>
## 8. 尝试 + 失败原因

| # | 方案 | LOC | Win fps | 结果 |
|---|------|----|---:|------|
| Phase A | 5 instrumentation 加 (TCP_NODELAY + sub-span + sampler) | ~80 | 26.9 → ? | NoDelay 是 root cause attempt,sub-span 加观测但不改 fps |
| T-B1 | per-actor transition conn 去 mutex | ~60 | 26.9 → 26.9 | Push mutex 已不是 bottleneck,T-B1 必要 but 不充分 |
| F1 | episode-granularity batch push | ~250 | 26.9 → 26.15 | 验证 push 不是 fps bottleneck (减 13x push count 但 fps 不动) |
| Path A SHM | cross-lang SHM inference (Phase 1-4) | ~1500 | 26.15 → 22.68 | ShmBridge master process GIL contention 反而拖慢 |

**累计 LOC ~1890,Win fps 净退化 (26.9 → 22.68)**。 ROI 严重负向。

**架构教训**: 我把 Go-actor 当作 master process 内的 daemon (cgo loaded + master IPC threads),不是 subprocess 隔离 (Python mp 模式)。 这是 fundamental implementation flaw,被多 LOC 优化遮蔽未发现。

---

<a name="redesign"></a>
## 9. 完全重设计 constraints

### 必须 (deal-breakers)

1. **Master process 不参与 IPC** — 像 Python mp 一样,actor 与 InfServer 直接 IPC,master 只 train + read buffer
2. **Buffer 跨进程 shm-backed** — actor 进 buffer 与 driver 读 buffer 不经 master 中转 (Python mp 用 SHMRing,Go-actor 也需 equiv)
3. **Per-call inference timing 双侧 instrumentation** — Python mp + Go-actor 都需 per-call RTT,可对比验
4. **Sub-process isolation 测试** — verify GIL contention is/isn't root cause

### 建议 (best practices)

5. **Foundation-first**: Path A 失败教训 — 不要在 1500 LOC 投入后才发现架构选错。 先 build minimum-viable pipeline (200 LOC),fair bench verify,再扩
6. **多 subagent-driven**: user 明示;复杂 task 用 opus model;每 phase 严格 reviewer + verify
7. **Python mp 当 reference**: 它的架构已 proven 40 fps Win,Go-actor 必须复制其架构 (不止 transport,还有 process isolation)
8. **Win box 是 truth source**: Mac variance 5x 太大,Mac 单 run 无意义

### Out-of-scope (本次不动)

- F1D4 opp minimax 优化 (P3 backlog)
- CUDA caching expandable_segments (Win+cu130 平台限制)
- 5 paradigm 全部迁 Go-actor (DMC 通了才考虑 AZ/PPO/CFR/BC)

---

<a name="open"></a>
## 10. Open questions / 待验

1. **Python mp 的 per-call inference RTT 是多少?** — 必须 instrument 才知,影响 hypothesis 闭环
2. **master process GIL contention 损失 多少 fps?** — 隔离测试 (无 training + 无 driver loop, 纯 actor inference + push,看 fps 是多少)
3. **Go-actor 在 subprocess (非 cgo) 模式下能跑多快?** — 假想 Go-actor 是独立 OS subprocess (如 Python mp 风格),与 master 走 mp.Queue,fps 是多少
4. **Go-actor cgo overhead 占比?** — 关键 cgo call (Run / start_pool / mem) wall time
5. **transition_sink_listener handler threads N=16 GIL 争 多少 ms/s?** — 无数据

## 11. 重设计候选路径(不预设倾向,user 决)

### R1: 复制 Python mp 架构 (Go-actor as subprocess)
- Go-actor 编 standalone executable,master process spawn N subprocess
- Subprocess 间走 mp.Queue / SHMRing (复用 Python mp infrastructure)
- 优点:架构 proven,GIL contention 自动解
- 缺点:Go subprocess 启动 cost,失去 cgo 共享 lib 优势,buffer integration 复杂

### R2: Master-IPC-free 重构 (bridge 全部移 InfServer subprocess)
- Path A repair + transition path 同样改造
- 优点:增量改 Phase 4 基础上,LOC ~300
- 缺点:验证待 instrument,可能仍有未识别 bottleneck

### R3: 完全 in-process (Go-actor + InfServer + driver 同一 process)
- 无 IPC,goroutine 直接 access network in-place via cgo callback
- 优点:零 IPC latency
- 缺点:cgo + GIL + Go runtime + torch 五者交互不可控;失败概率高

### R4: 接受 Python mp 胜
- 归档 I29,主线 回 Python mp + 优化它 (InfServer GPU pipeline / batching window 调优)
- 优点:基于 proven baseline 增量
- 缺点:不符 user goal "完全替代 Python"

---

## Appendix: 相关文件

- `openspec/changes/i29-go-actor-pool/perf_plan.md` — 原 plan (Phase A/B/C)
- `openspec/changes/i29-go-actor-pool/win_bench_audit.md` — T-C2 Win bench audit
- `openspec/changes/i29-go-actor-pool/shminf_design.md` — Path A SHM design
- `openspec/changes/i29-go-actor-pool/shminf_win_build.md` — Win SHM build steps
- `tools/_bench/mac_collector_results.md` — T-C1 Mac data
- `tools/_bench/win_results.md` — T-C2 Win TCP pre-F1 data
- `tools/_bench/win_f1_results.md` — Win TCP F1 data
- `tools/_bench/win_shm_results.md` — Win SHM Path A data
- `tools/_bench/run_mac_collector_pair.py` — Mac fair bench harness
- `tools/_bench/parse_win_bench.py` — Win bench metrics parser
