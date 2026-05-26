# I29 Redesign P2 — Mac fair bench acceptance FAILED

> ℹ **Historical record** — P2 fair bench at `f921f29` 失败 (Go 0.19x Python),后续 R2/R3/R5/R6 perf 调优 + R6.3 fairness fix + R7 architecture redesign 才达 acceptance。 final ratio: **1.54x** (5-seed,`post_r7_2_fair_5seed.md`)。 详 [[i29-r7-acceptance-ship]] 完整 progression。

**Date**: 2026-05-25  
**Commit**: `f921f29` (feature/i29-redesign, post P1.4 ship)  
**Hardware**: Mac M-series (darwin, CPU)  
**Config**: N=4 actor × 5 seed × 15s window,production v_legacy pool + DMCNetwork d_model=128

## Verdict: FAIL (structural)

Acceptance gate (per task spec):

| Metric | Required | Observed | Status |
|---|---|---|---|
| Go fps/actor mean ≥ Python mp baseline (48.1) × 1.00 | ≥ 48.10 | **9.76** | **FAIL** |
| Go fps_per_actor_std / fps_per_actor_mean ≤ 0.25 | ≤ 0.25 | **0.47** | **FAIL** |
| Go fps ≥ Python mp × 0.75 (structural floor) | ≥ 38.27 | 9.76 | **FAIL — structural** |

Per spec: 「若 Go fps < Python mp fps × 0.75 (< ~36 fps/actor):结构性问题,STOP + 落 root cause analysis到 tools/_bench/p2_results/FAIL_REPORT.md,**不 commit acceptance**」 — 此条件触发。

## Raw measurements

### Go subprocess (I29 redesign,DMCGoSubprocessCollector + cmd/gicg_actor + SHM ring)

| Seed | fps total | fps/actor | mem_delta | wall |
|---|---|---|---|---|
| 1 | 28.73 | 7.18 | +23 MB | 17.3s |
| 2 | 21.86 | 5.47 | +21 MB | 17.5s |
| 3 | 30.65 | 7.66 | +25 MB | 17.8s |
| 4 | 67.26 | 16.81 | +43 MB | 17.5s |
| 5 | 46.79 | 11.70 | +32 MB | 20.3s |
| **mean ± std** | **39.06 ± 18.22** | **9.76 ± 4.55** | +29 MB | — |
| CV (std/mean) | 0.47 | 0.47 | — | — |

### Python mp baseline (DMCMultiProcessCollector + SHMRing inference IPC)

| Seed | fps total | fps/actor | mem_delta | wall |
|---|---|---|---|---|
| 1 | 133.66 | 33.42 | +41 MB | 25.3s |
| 2 | 218.66 | 54.66 | +41 MB | 25.3s |
| 3 | 220.00 | 55.00 | +41 MB | 25.2s |
| 4 | 223.91 | 55.98 | +41 MB | 25.3s |
| 5 | 224.39 | 56.10 | +41 MB | 25.3s |
| **mean ± std** | **204.12 ± 39.47** | **51.03 ± 9.86** | +41 MB | — |
| CV | 0.19 | 0.19 | — | — |

**Ratio Go / Python mp = 0.19x (Go is 5.2x slower).**

(Note: seed 1 cold-start anomaly affects both backends, but Python mp recovers by seed 2;
Go variance persists across all seeds — high `mem_delta` correlates with high fps in Go
seed 4, suggesting GC churn frequency varies by seed.)

## Comparison vs prior cgo path baseline (mac_collector_results.md,2026-05-24,commit 9ba6311)

| Path | fps/actor mean ± std | n seeds | mem_delta |
|---|---|---|---|
| Go cgo (in-proc lib) | 12.75 ± 2.92 | 3 | +634 MB |
| **Go subprocess (P2,this report)** | **9.76 ± 4.55** | **5** | **+29 MB** |
| Python mp (cgo,2026-05-24) | 48.11 ± 11.98 | 3 | +41 MB |
| **Python mp (P2 re-run)** | **51.03 ± 9.86** | **5** | **+41 MB** |

**关键 finding**: 
- 子进程隔离 + SHM trans 把 master mem 从 +634 MB 拉到 +29 MB(✓ 大改善,与 5ep e2e
  invariant 一致)
- 但 fps/actor 并未提升 — 反而略低(12.75 → 9.76,在 stat 噪声内)
- Python mp baseline 稳定保持 ~5x faster

I29 redesign 解决了 **mem GC churn / deal-breaker invariant #1 (master 0 cgo)** 但
**未解决 production fps gap**。

## Root cause analysis

### 已确认 NOT the bottleneck

1. **SHM transport** — P0 layer 2 已证 cross-process push 与 Python within 4% stat tie
   (708K vs 693K ops/sec @ 12 KB payload),非 fps 主因。
2. **Subprocess overhead** — Go 子进程 spawn 一次 cold-start ~500ms,perf 测量 exclude
   bootstrap;运行期 OS process boundary 不再额外 cost。
3. **Inference batching** — InfServer max_batch=N_actors=4,batch_timeout=2ms,与
   Python mp 同 batching cfg。
4. **Game engine step rate** — Go DMC paradigm 跑同 game engine 同 cgo path,episode
   rate 一致(~0.17 eps/sec/actor 双路径),engine 非瓶颈。

### Likely root cause: **TCP inference RTT** (Go-only,Python mp 走 SHM)

Go-actor 走 **TCP socket** 向 InfServer 请求 inference(`InferenceClient` over TCP)。
Python mp actor 走 **SHMRing IPC**(`_DMCObsDictRemoteProvider` numpy 共享内存)。

每个 inference call wall:
- TCP localhost RTT: ~50-200 µs framing + syscall(实测 macOS loopback)
- SHMRing slot push+pop: ~2-5 µs(P0 layer 1 数据)
- → TCP path 比 SHM 慢 10-100x **per call**

每 episode inference call 频次:
- DMC me-turn 每步 1 forward call(选 action)
- f1d2 opponent 每步 ~depth-2 minimax 多 forward call(实测 ~10-50 calls/step opp)
- 每 ep ~3-19 trans × ~5-50 inf calls/trans ≈ 15-1000 inf calls

TCP RTT 累计:1000 calls × 100 µs = 100 ms / episode pure TCP latency。
Python mp SHM:1000 calls × 5 µs = 5 ms / episode → 节省 95 ms/ep。

@ N=4 + episode wall 1.5s(实测),TCP overhead 占 6.7% wall,但 inference 是串行打
batch_timeout 等队 — actor 在 send→recv 间 idle。 batch 满才 forward → N actor
互相等彼此到齐。 N=4 batch_timeout=2ms 命中率高,batch 满 1ms send 即 forward,
但 send→recv 仍走 TCP 单独 socket → 累积 latency。

Python mp SHMRing IPC 路径 forward 单 actor wall ~5 µs(P0),TCP forward ~200 µs:
**Python mp 单 forward 比 Go TCP 快 40x**。 episode 1000 forward → Python mp 5 ms,
Go TCP 200 ms,差 195 ms/ep × 0.17 eps/sec/actor = 33 ms wall/sec wasted on TCP
overhead per actor → ~30% throughput cost on Mac N=4。

实测 ratio 0.19x 意味 Go 还有其他 cost(可能 InfServer batching 在 mp.Process subproc
里 forward 同 SHM 路径并未对 Go 加速 — Go side TCP framing 仍是瓶颈)。

### Secondary: Go runtime overhead on Mac

prior memory note(2026-05-24)— Mac M4 unified-memory 下 Go runtime 13 OS threads
(sysmon + GC + GOMAXPROCS=10 P)vs Python mp child 2 threads → macOS scheduler
preference 偏 Python mp。 这是 layer 2 已 documented 4% gap 的来源,不解释 5x
gap,但叠加 TCP latency 是 contributing factor。

### Secondary: Per-episode wall variance

Go std/mean 0.47 vs Python mp 0.19 → Go 单 episode wall variance 大。 假设:f1d2
opponent minimax depth-2 树扩张 fan-out 强 seed-dependent(某 seed 触发深搜径远超
均值),Go side per-call TCP 累积放大此 variance。 Python mp SHM 路径 per-call
latency 低 + variance 低,被 batching 平滑。

## 不修复路径建议(用户决策)

I29 redesign 已 ship 的 **结构性收益**:
- master 0 cgo lib(deal-breaker invariant #1)
- mem +29 MB vs +634 MB(95% 收益,GC churn 已消除)
- Subprocess 隔离 — actor crash 不污染 master

但 production fps target 未达。 候选路径:

**R1**(放弃 fps gate)— 接受 Go 5x 慢于 Python mp,以 mem 收益换 isolation 收益。
适用场景:大 N(>8)Python mp InfServer 已是 CPU 瓶颈(已 documented
mac_collector_results.md:Python mp N=8 total fps 与 N=4 持平 ~222),Go subprocess
N=16+ 可水平扩展。 需 Win box N=16 验。

**R2**(SHM inference path)— Go-actor 改用 SHM IPC 向 InfServer 请求 inference(替代
TCP)。 LOC 估 ~300-500(Go side SHM client + Python InfServer SHM reader),实测预
期消除大部分 5x gap(SHM 比 TCP 40x faster per call)。 风险:Mac POSIX shm + Go
attach 已 P0 验过可行;production wire 是已知模式。

**R3**(放弃 Mac path)— Mac perf 不达 production gate,锁定 Win box 验收;Mac 仅 dev
本机 smoke。 production gate 走 Win box N=16+(historical Win Go 25 fps vs Python
35-37 fps,gap 28% — 比 Mac 5x 小很多,因 Win box 不同 OS scheduler / SHM
syscall cost 不同)。

**R4**(回滚 P1.4)— 撤销 I29 redesign 全栈,回 cgo path + master cgo lib。 不推荐
(放弃 deal-breaker invariant)。

## 验证 gates (本次 run)

```bash
# 单测 PASS
.venv/bin/python -m pytest training/core/actor/tests/test_go_subprocess_perf_smoke.py -v -m smoke_full
# → 1 passed in 17.43s

# Mac bench 完整 5 seed × 2 backend
.venv/bin/python -m tools._bench.run_mac_collector_pair --n-actors 4 --seeds 5 --out tools/_bench/p2_acceptance.md
# → 10 runs PASS,fps 数据落 p2_acceptance.md (生成但不 commit per FAIL 规则)
```

## Artifacts

- `tools/_bench/p2_acceptance.md` — auto-generated headline + per-seed table (本地 hold,**不 commit**)
- `training/core/actor/tests/test_go_subprocess_perf_smoke.py` — 新 perf smoke (commit)
- `tools/_bench/run_mac_collector_pair.py` — `_GO_TEST` 切换到 subprocess node (commit)
