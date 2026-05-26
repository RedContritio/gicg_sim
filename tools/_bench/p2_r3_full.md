# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `6cca1c9`  
Date: 2026-05-25 04:35  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 22.11 ± 16.03 | 5.53 ± 4.01 | +23 MB | 3 |
| 4 | python_mp | 211.88 ± 12.58 | 52.97 ± 3.15 | +41 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.10x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=3.67 fps/actor=0.92 mem_delta=+13MB wall=17.8s
- seed 2: fps=29.86 fps/actor=7.47 mem_delta=+23MB wall=18.2s
- seed 3: fps=32.79 fps/actor=8.20 mem_delta=+34MB wall=18.2s

**python_mp** (n=3)
- seed 1: fps=218.26 fps/actor=54.57 mem_delta=+41MB wall=25.3s
- seed 2: fps=197.39 fps/actor=49.35 mem_delta=+42MB wall=25.3s
- seed 3: fps=219.99 fps/actor=55.00 mem_delta=+41MB wall=25.3s
