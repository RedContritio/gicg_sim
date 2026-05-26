# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `660fc3d`  
Date: 2026-05-26 08:00  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|----------|---------|---------------------|---------------------------|----------------|--------|
| 4 | go | 20.97 ± 4.90 (23%) | 5.24 ± 1.23 (23%) | +21 MB | 3 |
| 4 | python_mp | 13.84 ± 2.89 (21%) | 3.46 ± 0.72 (21%) | +41 MB | 3 |
| 8 | go | 27.55 ± 18.97 (69%) | 3.44 ± 2.37 (69%) | +27 MB | 3 |
| 8 | python_mp | 30.44 ± 2.89 (10%) | 3.81 ± 0.36 (10%) | +41 MB | 3 |
| 16 | go | 30.06 ± 8.73 (29%) | 1.88 ± 0.54 (29%) | +33 MB | 3 |
| 16 | python_mp | 48.98 ± 8.23 (17%) | 3.06 ± 0.51 (17%) | +42 MB | 3 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 1.51x | Go faster |
| 8 | 0.90x | Python mp faster |
| 16 | 0.61x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=3)
- seed 1: fps=20.06 fps/actor=5.01 mem_delta=+20MB wall=17.2s
- seed 2: fps=26.26 fps/actor=6.57 mem_delta=+23MB wall=17.2s
- seed 3: fps=16.59 fps/actor=4.15 mem_delta=+20MB wall=17.9s

**python_mp** (n=3)
- seed 1: fps=16.93 fps/actor=4.23 mem_delta=+41MB wall=25.1s
- seed 2: fps=13.40 fps/actor=3.35 mem_delta=+41MB wall=25.2s
- seed 3: fps=11.20 fps/actor=2.80 mem_delta=+41MB wall=25.2s

### N=8

**go** (n=3)
- seed 1: fps=7.67 fps/actor=0.96 mem_delta=+19MB wall=17.9s
- seed 2: fps=45.45 fps/actor=5.68 mem_delta=+35MB wall=17.9s
- seed 3: fps=29.53 fps/actor=3.69 mem_delta=+27MB wall=21.1s

**python_mp** (n=3)
- seed 1: fps=31.13 fps/actor=3.89 mem_delta=+41MB wall=33.4s
- seed 2: fps=32.93 fps/actor=4.12 mem_delta=+41MB wall=33.4s
- seed 3: fps=27.27 fps/actor=3.41 mem_delta=+41MB wall=33.4s

### N=16

**go** (n=3)
- seed 1: fps=20.60 fps/actor=1.29 mem_delta=+33MB wall=17.4s
- seed 2: fps=37.80 fps/actor=2.36 mem_delta=+33MB wall=17.9s
- seed 3: fps=31.79 fps/actor=1.99 mem_delta=+32MB wall=18.0s

**python_mp** (n=3)
- seed 1: fps=56.40 fps/actor=3.52 mem_delta=+42MB wall=50.2s
- seed 2: fps=40.13 fps/actor=2.51 mem_delta=+41MB wall=50.9s
- seed 3: fps=50.40 fps/actor=3.15 mem_delta=+42MB wall=50.6s
