# I29 Win box fair bench — pure collector throughput

Commit: `7f7162c`
Date: 2026-05-26 08:56
Box: dev@192.0.2.10 (DEV-PC, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=12 | go | 51.44 ± 12.56 (24%) | 4.29 ± 1.05 (24%) | +18 MB | 3 |
| N=12 | python_mp | 34.73 ± 18.41 (53%) | 2.89 ± 1.53 (53%) | +7 MB | 3 |
| N=16 | go | 58.69 ± 2.82 (5%) | 3.67 ± 0.18 (5%) | +23 MB | 3 |
| N=16 | python_mp | 47.42 ± 4.10 (9%) | 2.96 ± 0.26 (9%) | +7 MB | 3 |
| N=20 | go | 54.19 ± 12.07 (22%) | 2.71 ± 0.60 (22%) | +25 MB | 3 |
| N=20 | python_mp | 29.62 ± 17.73 (60%) | 1.48 ± 0.88 (60%) | +6 MB | 3 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=12 | 1.48x | Go faster |
| N=16 | 1.24x | Go faster |
| N=20 | 1.83x | Go faster |

## Per-seed detail

### N=12

**go** (n=3)
- seed 1: fps=61.19 fps/actor=5.10 mem_delta=+24MB wall=20.4s
- seed 2: fps=55.86 fps/actor=4.66 mem_delta=+21MB wall=20.6s
- seed 3: fps=37.26 fps/actor=3.11 mem_delta=+10MB wall=20.6s

**python_mp** (n=3)
- seed 1: fps=50.26 fps/actor=4.19 mem_delta=+7MB wall=44.9s
- seed 2: fps=39.53 fps/actor=3.29 mem_delta=+6MB wall=45.0s
- seed 3: fps=14.40 fps/actor=1.20 mem_delta=+7MB wall=44.9s

### N=16

**go** (n=3)
- seed 1: fps=61.31 fps/actor=3.83 mem_delta=+23MB wall=20.8s
- seed 2: fps=59.06 fps/actor=3.69 mem_delta=+22MB wall=20.8s
- seed 3: fps=55.71 fps/actor=3.48 mem_delta=+24MB wall=20.7s

**python_mp** (n=3)
- seed 1: fps=47.27 fps/actor=2.95 mem_delta=+6MB wall=53.3s
- seed 2: fps=43.40 fps/actor=2.71 mem_delta=+7MB wall=53.3s
- seed 3: fps=51.60 fps/actor=3.22 mem_delta=+7MB wall=53.4s

### N=20

**go** (n=3)
- seed 1: fps=64.66 fps/actor=3.23 mem_delta=+27MB wall=25.5s
- seed 2: fps=56.91 fps/actor=2.85 mem_delta=+22MB wall=20.8s
- seed 3: fps=40.99 fps/actor=2.05 mem_delta=+26MB wall=20.9s

**python_mp** (n=3)
- seed 1: fps=50.06 fps/actor=2.50 mem_delta=+6MB wall=61.6s
- seed 2: fps=20.33 fps/actor=1.02 mem_delta=+7MB wall=61.8s
- seed 3: fps=18.46 fps/actor=0.92 mem_delta=+6MB wall=61.7s
