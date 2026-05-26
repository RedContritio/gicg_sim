# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `7157af3`  
Date: 2026-05-25 04:37  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 45.06 ± 9.85 | 11.27 ± 2.46 | +33 MB | 3 |
| 4 | python_mp | 180.32 ± 39.39 | 45.08 ± 9.85 | +41 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.25x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=53.92 fps/actor=13.48 mem_delta=+37MB wall=17.8s
- seed 2: fps=34.46 fps/actor=8.62 mem_delta=+28MB wall=17.6s
- seed 3: fps=46.79 fps/actor=11.70 mem_delta=+34MB wall=17.6s

**python_mp** (n=3)
- seed 1: fps=195.59 fps/actor=48.90 mem_delta=+41MB wall=25.3s
- seed 2: fps=209.79 fps/actor=52.45 mem_delta=+41MB wall=25.3s
- seed 3: fps=135.59 fps/actor=33.90 mem_delta=+41MB wall=25.4s
