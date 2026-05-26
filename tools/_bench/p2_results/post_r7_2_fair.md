# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `0036241`  
Date: 2026-05-25 13:59  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 17.86 ± 19.71 | 4.47 ± 4.93 | +16 MB | 3 |
| 4 | python_mp | 10.89 ± 5.99 | 2.72 ± 1.50 | +41 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 1.64x | Go faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=4.26 fps/actor=1.07 mem_delta=+6MB wall=18.4s
- seed 2: fps=40.47 fps/actor=10.12 mem_delta=+32MB wall=17.5s
- seed 3: fps=8.86 fps/actor=2.22 mem_delta=+11MB wall=17.6s

**python_mp** (n=3)
- seed 1: fps=16.53 fps/actor=4.13 mem_delta=+41MB wall=25.3s
- seed 2: fps=4.60 fps/actor=1.15 mem_delta=+40MB wall=25.2s
- seed 3: fps=11.53 fps/actor=2.88 mem_delta=+41MB wall=25.2s
