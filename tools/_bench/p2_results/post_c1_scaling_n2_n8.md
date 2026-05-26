# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `948fa99`  
Date: 2026-05-26 01:38  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|----------|---------|---------------------|---------------------------|----------------|--------|
| 2 | go | 9.21 ± 10.53 (114%) | 4.60 ± 5.26 (114%) | +8 MB | 5 |
| 2 | python_mp | 4.80 ± 3.04 (63%) | 2.40 ± 1.52 (63%) | +40 MB | 5 |
| 8 | go | 23.94 ± 7.41 (31%) | 2.99 ± 0.93 (31%) | +25 MB | 5 |
| 8 | python_mp | 36.11 ± 13.51 (37%) | 4.51 ± 1.69 (37%) | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 2 | 1.92x | Go faster |
| 8 | 0.66x | Python mp faster |

## Per-seed detail

### N=2

**go** (n=5)
- seed 1: fps=23.39 fps/actor=11.69 mem_delta=+14MB wall=21.4s
- seed 2: fps=3.87 fps/actor=1.93 mem_delta=+5MB wall=17.2s
- seed 3: fps=17.46 fps/actor=8.73 mem_delta=+13MB wall=17.2s
- seed 4: fps=0.60 fps/actor=0.30 mem_delta=+4MB wall=21.6s
- seed 5: fps=0.73 fps/actor=0.37 mem_delta=+4MB wall=17.8s

**python_mp** (n=5)
- seed 1: fps=3.67 fps/actor=1.83 mem_delta=+40MB wall=21.0s
- seed 2: fps=10.07 fps/actor=5.03 mem_delta=+40MB wall=21.1s
- seed 3: fps=2.53 fps/actor=1.27 mem_delta=+39MB wall=21.1s
- seed 4: fps=3.13 fps/actor=1.57 mem_delta=+39MB wall=21.1s
- seed 5: fps=4.60 fps/actor=2.30 mem_delta=+40MB wall=21.1s

### N=8

**go** (n=5)
- seed 1: fps=27.45 fps/actor=3.43 mem_delta=+29MB wall=20.0s
- seed 2: fps=23.06 fps/actor=2.88 mem_delta=+22MB wall=20.4s
- seed 3: fps=11.40 fps/actor=1.42 mem_delta=+23MB wall=17.3s
- seed 4: fps=29.19 fps/actor=3.65 mem_delta=+25MB wall=20.7s
- seed 5: fps=28.59 fps/actor=3.57 mem_delta=+27MB wall=17.6s

**python_mp** (n=5)
- seed 1: fps=30.40 fps/actor=3.80 mem_delta=+41MB wall=33.4s
- seed 2: fps=33.60 fps/actor=4.20 mem_delta=+41MB wall=33.4s
- seed 3: fps=27.27 fps/actor=3.41 mem_delta=+41MB wall=33.4s
- seed 4: fps=29.33 fps/actor=3.67 mem_delta=+41MB wall=33.5s
- seed 5: fps=59.93 fps/actor=7.49 mem_delta=+41MB wall=33.4s
