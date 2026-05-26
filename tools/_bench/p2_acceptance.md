# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `f8b491e`  
Date: 2026-05-25 04:30  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 45.44 ± 12.78 | 11.36 ± 3.20 | +33 MB | 5 |
| 4 | python_mp | 153.23 ± 35.74 | 38.31 ± 8.93 | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 0.30x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=5)
- seed 1: fps=38.80 fps/actor=9.70 mem_delta=+28MB wall=17.9s
- seed 2: fps=35.85 fps/actor=8.96 mem_delta=+28MB wall=17.8s
- seed 3: fps=47.27 fps/actor=11.82 mem_delta=+33MB wall=17.7s
- seed 4: fps=38.33 fps/actor=9.58 mem_delta=+29MB wall=17.5s
- seed 5: fps=66.96 fps/actor=16.74 mem_delta=+45MB wall=17.3s

**python_mp** (n=5)
- seed 1: fps=144.59 fps/actor=36.15 mem_delta=+41MB wall=25.7s
- seed 2: fps=140.85 fps/actor=35.21 mem_delta=+42MB wall=25.6s
- seed 3: fps=130.66 fps/actor=32.67 mem_delta=+42MB wall=25.9s
- seed 4: fps=133.66 fps/actor=33.42 mem_delta=+41MB wall=25.3s
- seed 5: fps=216.38 fps/actor=54.10 mem_delta=+41MB wall=25.5s
