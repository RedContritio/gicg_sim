# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `0bba1a6`  
Date: 2026-05-25 04:41  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 32.26 ± 9.64 | 8.07 ± 2.41 | +27 MB | 3 |
| 4 | python_mp | 203.99 ± 26.23 | 51.00 ± 6.56 | +41 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.16x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=36.72 fps/actor=9.18 mem_delta=+29MB wall=17.8s
- seed 2: fps=38.86 fps/actor=9.72 mem_delta=+27MB wall=17.4s
- seed 3: fps=21.19 fps/actor=5.30 mem_delta=+25MB wall=17.4s

**python_mp** (n=3)
- seed 1: fps=218.26 fps/actor=54.57 mem_delta=+41MB wall=25.3s
- seed 2: fps=173.72 fps/actor=43.43 mem_delta=+41MB wall=25.3s
- seed 3: fps=220.00 fps/actor=55.00 mem_delta=+41MB wall=25.3s
