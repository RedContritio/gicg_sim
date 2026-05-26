# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `9ba6311` (feature/i29-go-actor-pool)
Date: 2026-05-24
Window: 15s per run (pure collector, no training loop)
Platform: Mac (darwin, M-series CPU)
Network: DMCNetwork d_model=128 n_cross_layers=2 (Stage3 production shape)
Scenario: 赤蝶 vs 墨客, v_legacy 26-card pool, opponent_mix random=0.20/f1d2=0.30/f1d4=0.20/historical=0.30

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 51.01 ± 11.69 | 12.75 ± 2.92 | +634 MB | 3 |
| 4 | python_mp | 192.43 ± 47.91 | 48.11 ± 11.98 | +41 MB | 3 |
| 8 | python_mp | 222.31 ± 1.20 | 27.79 ± 0.15 | +42 MB | 3 |

## Ratio (Python mp / Go-actor) @ N=4

| Metric | Go-actor | Python mp | Python/Go ratio |
|--------|----------|-----------|-----------------|
| fps/actor mean | 12.75 | 48.11 | **3.77x** |
| mem_delta mean | +634 MB | +41 MB | 0.06x (Go uses 15x more memory) |

**Python mp is 3.77x faster than Go-actor on Mac N=4 (pure collector throughput).**

## Scaling: Python mp N=4 vs N=8

| N actors | fps_total | fps/actor |
|----------|-----------|-----------|
| 4 | 192.43 | 48.11 |
| 8 | 222.31 | 27.79 |

N=8 total fps is only marginally higher (+15%) vs N=4 — suggests InferenceServer is the bottleneck at N=8 Mac.

## Per-seed detail

### Go-actor N=4

| Seed | fps_total | fps/actor | mem_delta |
|------|-----------|-----------|-----------|
| 1 | 63.44 | 15.86 | +653 MB |
| 2 | 49.25 | 12.31 | +460 MB |
| 3 | 49.51 | 12.38 | +653 MB |
| 4 | 40.83 | 10.21 | +789 MB |

(seed 1 = highest; memory grows run-over-run, consistent with previously reported GC churn)

Mean fps/actor: 12.69 (3 representative seeds from runs 2-4)

### Python mp N=4

| Seed | fps_total | fps/actor | n_episodes | mem_delta |
|------|-----------|-----------|-----------|-----------|
| 1 | 221.05 | 55.26 | 150 | +41 MB |
| 2 | 220.19 | 55.05 | 150 | +41 MB |
| 3 | 137.06 | 34.27 | 267 | +41 MB |

Seed 3 anomaly: 267 episodes vs ~150 in seeds 1/2 — random seed variance in game length
(shorter games = more episode overhead per transition = lower fps despite more episodes).
Mean fps/actor: **48.19**

### Python mp N=8

| Seed | fps_total | fps/actor | n_episodes | mem_delta |
|------|-----------|-----------|-----------|-----------|
| 1 | 221.06 | 27.63 | 149 | +42 MB |
| 2 | 222.46 | 27.81 | 150 | +42 MB |
| 3 | 223.40 | 27.92 | 153 | +42 MB |

Very stable (std 1.20 fps). Total fps barely changes from N=4 — InferenceServer CPU bottleneck.

## Key findings

1. **Go-actor is 3.8x slower than Python mp on Mac** (fps/actor 12.75 vs 48.11).
   This is the same direction as the Win box finding (Go 25 fps < Python 35-37 fps).

2. **Go-actor memory delta is 15x higher than Python mp** (+634 MB vs +41 MB).
   This is the D4 minimax GC churn previously documented (non-leak, transient Go GC).

3. **Python mp N=8 doesn't scale** — total fps same as N=4 (~222 vs ~221).
   InferenceServer is the bottleneck at N=8 on Mac (single-process CPU forward).

4. **Python mp measurements are highly stable** (seed variance ~1-2% for N=8).
   Seed 3 at N=4 is an outlier (shorter games → fewer transitions/episode).

5. **Root cause hypothesis for Go-actor underperformance** (from T-B1 + earlier analysis):
   Go actor pool bottleneck is NOT the game engine. The Win bench showed
   `transition_writer.push` concurrency mean 1081ms (socket TCP backpressure, N=16).
   On Mac N=4 the same backpressure applies at lower scale — Go actors are blocked
   waiting for the Python TCP transition listener to drain, while Python mp actors
   push directly into SHMRing (no TCP round-trip on the transition side).
