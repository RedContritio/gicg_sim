# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `fefe945`  
Date: 2026-05-25 15:05  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std | fps/actor mean ± std | mem_delta mean | n runs |
|----------|---------|---------------|---------------------|----------------|--------|
| 4 | go | 19.92 ± 13.39 | 4.98 ± 3.35 | +18 MB | 5 |
| 4 | python_mp | 12.93 ± 3.90 | 3.23 ± 0.97 | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 1.54x | Go faster |

## Per-seed detail

### N=4

**go** (n=5)
- seed 1: fps=5.27 fps/actor=1.32 mem_delta=+10MB wall=18.2s
- seed 2: fps=29.85 fps/actor=7.46 mem_delta=+25MB wall=17.6s
- seed 3: fps=20.73 fps/actor=5.18 mem_delta=+17MB wall=17.6s
- seed 4: fps=7.80 fps/actor=1.95 mem_delta=+11MB wall=17.7s
- seed 5: fps=35.93 fps/actor=8.98 mem_delta=+26MB wall=18.3s

**python_mp** (n=5)
- seed 1: fps=16.93 fps/actor=4.23 mem_delta=+41MB wall=25.2s
- seed 2: fps=8.60 fps/actor=2.15 mem_delta=+41MB wall=25.2s
- seed 3: fps=11.27 fps/actor=2.82 mem_delta=+41MB wall=25.2s
- seed 4: fps=10.67 fps/actor=2.67 mem_delta=+41MB wall=25.2s
- seed 5: fps=17.20 fps/actor=4.30 mem_delta=+41MB wall=25.2s
