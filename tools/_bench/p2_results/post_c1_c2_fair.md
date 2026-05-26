# I29 T-C1 Mac fair bench — pure collector throughput

> ℹ **Historical record — Go/Py = 0.68x reveals structural defect**。 post-C1+C2+I2 fix 后 ratio 反转 (pre-audit "3.66x" → 0.68x),暴露 1 Go subprocess containing N goroutine + InferenceShmBridge layer 的 structural overhead 不可挽回。 R7 architecture redesign (R7.1 删 bridge + R7.2 N independent subprocess) 后 ratio MET: **1.54x** (`post_r7_2_fair_5seed.md`)。 详 [[i29-r7-acceptance-ship]] bench progression table。

Commit: `2b44d8d`  
Date: 2026-05-25 13:04  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 8.38 ± 1.08 | 2.09 ± 0.27 | +12 MB | 3 |
| 4 | python_mp | 12.31 ± 4.94 | 3.08 ± 1.24 | +41 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.68x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=9.00 fps/actor=2.25 mem_delta=+14MB wall=20.8s
- seed 2: fps=7.13 fps/actor=1.78 mem_delta=+9MB wall=17.2s
- seed 3: fps=9.00 fps/actor=2.25 mem_delta=+12MB wall=18.5s

**python_mp** (n=3)
- seed 1: fps=16.13 fps/actor=4.03 mem_delta=+41MB wall=25.2s
- seed 2: fps=14.07 fps/actor=3.52 mem_delta=+40MB wall=25.2s
- seed 3: fps=6.73 fps/actor=1.68 mem_delta=+41MB wall=25.2s
