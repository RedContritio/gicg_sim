# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `da07c10`  
Date: 2026-05-26 05:39  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|----------|---------|---------------------|---------------------------|----------------|--------|
| 2 | go | 9.04 ± 7.17 (79%) | 4.52 ± 3.58 (79%) | +8 MB | 5 |
| 2 | python_mp | 6.64 ± 4.06 (61%) | 3.32 ± 2.03 (61%) | +39 MB | 5 |
| 4 | go | 17.71 ± 8.44 (48%) | 4.43 ± 2.11 (48%) | +17 MB | 5 |
| 4 | python_mp | 10.24 ± 4.59 (45%) | 2.56 ± 1.15 (45%) | +41 MB | 5 |
| 8 | go | 40.79 ± 25.52 (63%) | 5.10 ± 3.19 (62%) | +35 MB | 5 |
| 8 | python_mp | 33.81 ± 16.85 (50%) | 4.23 ± 2.11 (50%) | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 2 | 1.36x | Go faster |
| 4 | 1.73x | Go faster |
| 8 | 1.21x | Go faster |

## Per-seed detail

### N=2

**go** (n=5)
- seed 1: fps=15.46 fps/actor=7.73 mem_delta=+10MB wall=18.6s
- seed 2: fps=3.60 fps/actor=1.80 mem_delta=+6MB wall=17.8s
- seed 3: fps=18.13 fps/actor=9.06 mem_delta=+13MB wall=20.5s
- seed 4: fps=3.20 fps/actor=1.60 mem_delta=+5MB wall=17.3s
- seed 5: fps=4.80 fps/actor=2.40 mem_delta=+6MB wall=17.3s

**python_mp** (n=5)
- seed 1: fps=3.73 fps/actor=1.87 mem_delta=+39MB wall=21.0s
- seed 2: fps=10.53 fps/actor=5.27 mem_delta=+41MB wall=21.1s
- seed 3: fps=8.27 fps/actor=4.13 mem_delta=+39MB wall=21.0s
- seed 4: fps=9.60 fps/actor=4.80 mem_delta=+39MB wall=21.1s
- seed 5: fps=1.07 fps/actor=0.53 mem_delta=+39MB wall=21.0s

### N=4

**go** (n=5)
- seed 1: fps=13.93 fps/actor=3.48 mem_delta=+16MB wall=17.3s
- seed 2: fps=30.39 fps/actor=7.60 mem_delta=+23MB wall=17.3s
- seed 3: fps=19.79 fps/actor=4.95 mem_delta=+17MB wall=17.3s
- seed 4: fps=17.00 fps/actor=4.25 mem_delta=+16MB wall=17.3s
- seed 5: fps=7.46 fps/actor=1.87 mem_delta=+11MB wall=17.8s

**python_mp** (n=5)
- seed 1: fps=17.47 fps/actor=4.37 mem_delta=+41MB wall=25.1s
- seed 2: fps=8.13 fps/actor=2.03 mem_delta=+41MB wall=25.1s
- seed 3: fps=11.67 fps/actor=2.92 mem_delta=+41MB wall=25.1s
- seed 4: fps=5.53 fps/actor=1.38 mem_delta=+40MB wall=25.2s
- seed 5: fps=8.40 fps/actor=2.10 mem_delta=+41MB wall=25.1s

### N=8

**go** (n=5)
- seed 1: fps=80.30 fps/actor=10.04 mem_delta=+56MB wall=17.8s
- seed 2: fps=29.73 fps/actor=3.72 mem_delta=+25MB wall=20.9s
- seed 3: fps=10.53 fps/actor=1.32 mem_delta=+22MB wall=17.3s
- seed 4: fps=43.32 fps/actor=5.41 mem_delta=+36MB wall=17.3s
- seed 5: fps=40.05 fps/actor=5.01 mem_delta=+35MB wall=17.3s

**python_mp** (n=5)
- seed 1: fps=31.60 fps/actor=3.95 mem_delta=+41MB wall=33.3s
- seed 2: fps=32.93 fps/actor=4.12 mem_delta=+41MB wall=33.3s
- seed 3: fps=14.80 fps/actor=1.85 mem_delta=+41MB wall=33.3s
- seed 4: fps=28.67 fps/actor=3.58 mem_delta=+41MB wall=33.3s
- seed 5: fps=61.06 fps/actor=7.63 mem_delta=+41MB wall=33.3s
