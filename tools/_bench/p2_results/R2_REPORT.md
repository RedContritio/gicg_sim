# I29 Redesign R2 — InferenceShmBridge in InfServer subprocess (TCP→SHM inference)

> ⚠ **SUPERSEDED — SHM inference path retired in R7.1** (commit `ff50548`, 2026-05-25)。 `InferenceShmBridge` thread layer 引入额外 hop 是 post-C1+C2+I2 0.68x ratio 的 structural 嫌疑之一,R7.1 删整 SHM inference path 回 TCP only,与 Python mp wire 等价 (零桥)。 详 [[i29-r7-acceptance-ship]] / `openspec/specs/training-architecture/actor-backend.md` AB7-AB9。

**Date**: 2026-05-25
**Commit**: post `6cca1c9` (3-commit R2 stack: server move + pipeline wire + DMC default)
**Hardware**: Mac M-series (darwin, CPU)
**Config**: N=4 actor × 5 seed × 15s window, production v_legacy pool + DMCNetwork d_model=128
**Path under test**: DMCGoSubprocessCollector + cmd/gicg_actor SHM inference + InfServer subprocess SHM bridge

## Verdict: FAIL acceptance gate, PASS architecture

| Metric | Required | Observed | Status |
|---|---|---|---|
| Go fps/actor mean ≥ Python mp baseline × 1.00 | ≥ 38.31 (this run) / 48.10 (FAIL_REPORT baseline) | **11.36** | **FAIL** |
| Go fps_per_actor_std / fps_per_actor_mean ≤ 0.25 | ≤ 0.25 | **0.28** | **FAIL** |
| Architecture invariant #1 (master 0 IPC threads) on SHM path | required | satisfied | **PASS** |
| 5 ep e2e wall (Mac N=2) — SHM vs TCP | SHM ≤ TCP | SHM 1.21s ≤ TCP 2.0s | **PASS** |

## R2 vs pre-R2 (TCP path) comparison

| Path | fps/actor mean ± std | CV | mem_delta | ratio vs Python mp |
|---|---|---|---|---|
| Pre-R2 TCP (commit `f921f29` baseline) | 9.76 ± 4.55 | 0.47 | +29 MB | **0.19x** |
| **R2 SHM (this report)** | **11.36 ± 3.20** | **0.28** | **+33 MB** | **0.30x** |
| Python mp baseline (this run) | 38.31 ± 8.93 | 0.23 | +41 MB | 1.00x |

**R2 alone gain: +16% fps, -40% CV** — SHM inference transport materially improves
on TCP per the IPC theory (SHM ~5µs vs TCP ~100µs round-trip from P0 layers 1+2),
but the absolute gap to Python mp remains structural.

## R2 5 ep e2e wall (SHM vs TCP)

Single Mac N=2 run, production-shape v_legacy paradigm (pure random opponent — no
minimax inference amplification — to isolate inference transport cost):

| Mode | 5 ep wall | n_trans | trans/sec/actor |
|---|---|---|---|
| SHM (R2 default) | 1.21s | 73 | 30.2 |
| TCP (legacy fallback) | 2.0s (per FAIL_REPORT baseline) | ~80 | ~20 |

R2 SHM is **~40% faster wall-clock** for pure-random episodes where inference
transport dominates and minimax fan-out is absent.

## Raw measurements (P2 acceptance bench)

### Go subprocess (R2 SHM path) — 5 seed × N=4 × 15s

| Seed | fps total | fps/actor | mem_delta | wall |
|---|---|---|---|---|
| 1 | 38.80 | 9.70 | +28 MB | 17.9s |
| 2 | 35.85 | 8.96 | +28 MB | 17.8s |
| 3 | 47.27 | 11.82 | +33 MB | 17.7s |
| 4 | 38.33 | 9.58 | +29 MB | 17.5s |
| 5 | 66.96 | 16.74 | +45 MB | 17.3s |
| **mean ± std** | **45.44 ± 12.78** | **11.36 ± 3.20** | +33 MB | — |

### Python mp baseline — 5 seed × N=4 × 15s (same commit, same hardware, same harness)

| Seed | fps total | fps/actor | mem_delta | wall |
|---|---|---|---|---|
| 1 | 144.59 | 36.15 | +41 MB | 25.7s |
| 2 | 140.85 | 35.21 | +42 MB | 25.6s |
| 3 | 130.66 | 32.67 | +42 MB | 25.9s |
| 4 | 133.66 | 33.42 | +41 MB | 25.3s |
| 5 | 216.38 | 54.10 | +41 MB | 25.5s |
| **mean ± std** | **153.23 ± 35.74** | **38.31 ± 8.93** | +41 MB | — |

(Per-seed variance is real on both backends — seed 5 is an outlier across both, likely
because that seed lands on shorter minimax-heavy episodes; the variance is not a Go-only
artifact.)

## Root cause analysis (why R2 alone doesn't close the gap)

### Confirmed: SHM transport is faster than TCP (✓)

- P0 Layer 1 micro-bench (pure ring push/pop): Go SHM 4.4-19.5× Python (cf65cf2)
- P0 Layer 2 cross-process bench: Go vs Python ~4% stat tie (650f1b5)
- R2 production: TCP path 9.76 → SHM path 11.36 fps/actor (~16% improvement)
- 5ep pure-random wall: 2.0s → 1.21s (-40%)

### Confirmed: bridge in subprocess is structurally sound (✓)

- master process load test: `lsof` shows 0 libgicg / libgicg_actor mmap (5ep e2e
  test invariant check passes)
- bridge thread runs inside InfServer mp.Process subprocess sharing GIL with
  batched-forward loop — no contention with master train loop
- bridge join + ring close happens in `_server_loop` tail before subprocess exit
  (no leak; verified via test cycle)

### Likely remaining bottleneck #1: bridge serialization defeats batching

The bridge is a **single thread** that:
1. Drains 1 req from req_ring per loop iter → puts into request_q
2. Drains response_qs (round-robin N actors) → writes resp_rings

With N=4 actors pushing concurrently to the shared MPSC req_ring, the bridge
processes them serially. Each `_handle_request` does:
- `decode_infer_request` (parse wire bytes → InferRequest struct)
- `socket_request_to_pickled_payload` (build numpy dict + `pickle.dumps(~125 KB)`)
- `request_q.put` (mp.Queue inter-thread put)

Each step takes 100-500µs. So N requests → 0.5-2ms serial pickle overhead.
`_server_loop` batches with `batch_timeout_ms=2`. With bridge taking 0.5-2ms per
request, requests trickle into request_q just slow enough that batch fill often
exits on timeout with batch_size ≤ 2 instead of 4.

Attempted in-bridge bulk-drain (one loop iter pops up to N from req_ring +
forwards each) made things WORSE (4.79 vs 11.36 fps/actor) — likely because
pickle-then-put serial overhead climbs to N×pickle latency before bridge
yields to drain responses, starving response delivery and stalling actors.

### Likely remaining bottleneck #2: deep game engine alloc-per-step

Per the previous session's micro-bench (`gicg_engine/tests/game_perf_bench_test.go`,
commit 3b47cfd): each `Game.Step` allocates **821 small objects on average**
(state machine + hook dispatch + temporary slices). At 100s of steps per episode
× N actors, GC pressure becomes a wall-clock cost not addressed by IPC fixes.

R3 attempt (`gicg_engine.SnapshotPooled` sync.Pool API, commits cb91ab2/b663383)
reduced micro-bench alloc count by 16 (~2%) and wall by 15%, but most allocations
live deeper in `Game.Step` itself — `sync.Pool` at the snapshot boundary doesn't
reach them. Closing 5× would need ~1000+ LOC engine-internal redesign.

### Likely remaining bottleneck #3: Mac OS thread scheduling preference

Prior memory (2026-05-24): Go runtime spawns ~13 OS threads on Mac (sysmon + GC
+ GOMAXPROCS=10 P-threads) vs Python mp child = 2 threads. macOS scheduler on
Mac M-series unified memory tends to favor Python's thread profile under CPU-bound
workloads. This was documented as a ~4% Layer 2 cost; it doesn't explain 5× but
compounds with #1 and #2.

## What R2 achieved

1. **Architecture invariant #1 satisfied on SHM path** — master process never
   touches SHM inference rings (extends Phase 1-4 invariant established for the
   transition ring to the inference ring family).
2. **Bridge moved out of master process** — eliminates the GIL contention concern
   that motivated the redesign vs the original `feature/i29-go-actor-shminf`
   approach.
3. **+16% production fps + -40% production CV** vs pre-R2 TCP path.
4. **-40% wall on pure-random 5ep e2e** vs TCP path (where transport dominates).
5. **TCP fallback path retained** for diagnostic / future hardware where TCP may
   compare differently (`inference_mode='tcp'` in DMCGoSubprocessCollector).

## What R2 did NOT achieve

1. Layer 3 production gate `fps/actor ≥ 48.1 × 1.00` — observed 11.36 (0.30×).
2. CV gate `≤ 0.25` — observed 0.28 (close but over).
3. Closing the structural gap on minimax-heavy mixed-opponent workloads.

## Recommendation

R2 is committed as the right architectural path (per the spec's "if FAIL, the
path is still right, just deeper bottleneck"). Closing Layer 3 gate on Mac N=4
requires layered work beyond R2:

- **R4 (in scope of next session, ~500-1000 LOC)**: Pure-SHM main loop in
  `_server_loop` — bypass request_q + response_qs entirely when in SHM-only mode.
  Direct path: req_ring drain → decoder → forward → resp_ring write. Eliminates
  pickle (bridge step), mp.Queue (request/response), and bridge-as-bottleneck.
  Requires `decode_dmc_request` to accept the raw socket InferRequest bytes
  (currently expects pickled dict).
- **R5 (deep engine work, ~1000+ LOC)**: Reduce `Game.Step` alloc count from 821
  to <100 by switching hook dispatch + state machine to zero-alloc patterns.
- **R6 (out of scope)**: Re-validate on Mac N=16+ or Win box where Go runtime
  scaling and Mac scheduler effects are less dominant.

The user's challenge — "Go不应比 Python 慢" — remains valid in principle (Layers
1+2 verify Go IPC IS faster), but the Layer 3 gap is not single-fault. R2
closes one fault (IPC); R4-R6 are needed for the rest.

## Verification commands (this run)

```bash
# Go test suite
go test ./gicg_actor/... ./cmd/gicg_actor/ -count=1
# All pass.

# Python integration tests
.venv/bin/python -m pytest \
    training/core/actor/tests/test_go_subprocess_spawn.py \
    training/core/actor/tests/test_go_subprocess_shm_e2e.py \
    training/core/actor/tests/test_inference_shm_bridge.py \
    training/paradigms/dmc/tests/test_go_subprocess_1ep_smoke.py \
    training/paradigms/dmc/tests/test_go_subprocess_5ep_e2e.py -v
# 13 passed.

# Smoke
.venv/bin/python -m pytest -m smoke training/tests/ -q
# 5 passed.

# P2 acceptance
.venv/bin/python -m tools._bench.run_mac_collector_pair \
    --n-actors 4 --seeds 5 --out tools/_bench/p2_acceptance.md
# Results: see tables above + tools/_bench/p2_acceptance.md
```

## Artifacts

- `tools/_bench/p2_acceptance.md` — full per-seed acceptance bench output
- `tools/_bench/p2_results/R2_REPORT.md` — this file
- `tools/_bench/p2_results/FAIL_REPORT.md` — pre-R2 (TCP) baseline FAIL report
- `tools/_bench/p0_results/SUMMARY.md` — 3-layer perf summary (Layer 1-3)
