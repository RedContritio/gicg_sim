# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `cb91ab2`  
Date: 2026-05-25 04:23  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 16.75 ± 4.22 | 4.19 ± 1.06 | +17 MB | 3 |
| 4 | python_mp | 160.59 ± 54.51 | 40.15 ± 13.62 | +42 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.10x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=12.13 fps/actor=3.03 mem_delta=+16MB wall=17.6s
- seed 2: fps=20.39 fps/actor=5.10 mem_delta=+18MB wall=17.7s
- seed 3: fps=17.73 fps/actor=4.43 mem_delta=+18MB wall=18.0s

**python_mp** (n=3)
- seed 1: fps=217.05 fps/actor=54.26 mem_delta=+41MB wall=25.3s
- seed 2: fps=156.45 fps/actor=39.11 mem_delta=+43MB wall=25.9s
- seed 3: fps=108.27 fps/actor=27.07 mem_delta=+41MB wall=26.5s
