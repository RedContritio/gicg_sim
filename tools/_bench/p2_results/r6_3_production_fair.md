# I29 T-C1 Mac fair bench — pure collector throughput

> ⚠ **SUPERSEDED — Algorithm asymmetry artifact**:本 bench Go side 走 hardcoded `minimaxNodeBudget=4000` (D4 截到 ~D2.7 effective),Python side 跑 full D4 uncapped — 11.23 vs 3.07 = "Go ~D2.7 vs Python full D4" 算法 shortcut wall-time 差,不是纯 pipeline overhead。 post-C2 fix (budget cfg-driven 双侧对齐) + R7 architecture redesign 后,真 robust ratio = **1.54x** (5-seed,见 `post_r7_2_fair_5seed.md`)。 详 [[i29-r7-acceptance-ship]] / [[audit-reviews-reveal-perf-artifacts]]。

Commit: `e73312f`  
Date: 2026-05-25 10:59  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 44.93 ± 10.95 | 11.23 ± 2.74 | +36 MB | 5 |
| 4 | python_mp | 12.28 ± 5.46 | 3.07 ± 1.36 | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 3.66x | Go faster |

## Per-seed detail

### N=4

**go** (n=5)
- seed 1: fps=45.25 fps/actor=11.31 mem_delta=+33MB wall=17.5s
- seed 2: fps=48.78 fps/actor=12.20 mem_delta=+37MB wall=17.6s
- seed 3: fps=26.46 fps/actor=6.61 mem_delta=+31MB wall=18.8s
- seed 4: fps=48.86 fps/actor=12.21 mem_delta=+37MB wall=17.5s
- seed 5: fps=55.31 fps/actor=13.83 mem_delta=+40MB wall=17.5s

**python_mp** (n=5)
- seed 1: fps=16.53 fps/actor=4.13 mem_delta=+41MB wall=25.2s
- seed 2: fps=12.20 fps/actor=3.05 mem_delta=+41MB wall=25.2s
- seed 3: fps=11.27 fps/actor=2.82 mem_delta=+41MB wall=25.2s
- seed 4: fps=3.80 fps/actor=0.95 mem_delta=+40MB wall=25.2s
- seed 5: fps=17.60 fps/actor=4.40 mem_delta=+41MB wall=25.2s
