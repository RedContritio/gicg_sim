# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 11:12
Box: dev@192.0.2.10 (DEV-PC, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=14 | python_mp | 42.35 ± 16.66 (39%) | 3.02 ± 1.19 (39%) | +7 MB | 5 |
| N=16 | python_mp | 38.65 ± 10.93 (28%) | 2.42 ± 0.68 (28%) | +7 MB | 5 |
| N=18 | python_mp | 50.06 ± 2.71 (5%) | 2.78 ± 0.15 (5%) | +7 MB | 5 |
| N=19 | python_mp | 51.00 ± 2.99 (6%) | 2.68 ± 0.16 (6%) | +7 MB | 5 |
| N=20 | python_mp | 48.93 ± 4.80 (10%) | 2.45 ± 0.24 (10%) | +7 MB | 5 |
| N=22 | python_mp | 48.61 ± 1.48 (3%) | 2.21 ± 0.07 (3%) | +6 MB | 5 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=14 | N/A | insufficient data |
| N=16 | N/A | insufficient data |
| N=18 | N/A | insufficient data |
| N=19 | N/A | insufficient data |
| N=20 | N/A | insufficient data |
| N=22 | N/A | insufficient data |

## Per-seed detail

### N=14

**python_mp** (n=5)
- seed 1: fps=51.73 fps/actor=3.69 mem_delta=+7MB wall=49.2s
- seed 2: fps=41.26 fps/actor=2.95 mem_delta=+7MB wall=49.1s
- seed 3: fps=13.87 fps/actor=0.99 mem_delta=+7MB wall=49.1s
- seed 4: fps=50.67 fps/actor=3.62 mem_delta=+6MB wall=49.1s
- seed 5: fps=54.20 fps/actor=3.87 mem_delta=+7MB wall=49.1s

### N=16

**python_mp** (n=5)
- seed 1: fps=43.60 fps/actor=2.72 mem_delta=+7MB wall=53.3s
- seed 2: fps=39.33 fps/actor=2.46 mem_delta=+7MB wall=53.3s
- seed 3: fps=22.20 fps/actor=1.39 mem_delta=+6MB wall=53.3s
- seed 4: fps=51.93 fps/actor=3.25 mem_delta=+7MB wall=53.3s
- seed 5: fps=36.20 fps/actor=2.26 mem_delta=+6MB wall=53.4s

### N=18

**python_mp** (n=5)
- seed 1: fps=50.46 fps/actor=2.80 mem_delta=+7MB wall=57.5s
- seed 2: fps=46.20 fps/actor=2.57 mem_delta=+7MB wall=57.5s
- seed 3: fps=49.00 fps/actor=2.72 mem_delta=+6MB wall=57.8s
- seed 4: fps=51.13 fps/actor=2.84 mem_delta=+7MB wall=57.5s
- seed 5: fps=53.53 fps/actor=2.97 mem_delta=+6MB wall=57.5s

### N=19

**python_mp** (n=5)
- seed 1: fps=51.13 fps/actor=2.69 mem_delta=+7MB wall=59.6s
- seed 2: fps=49.53 fps/actor=2.61 mem_delta=+7MB wall=59.5s
- seed 3: fps=49.80 fps/actor=2.62 mem_delta=+7MB wall=59.6s
- seed 4: fps=48.46 fps/actor=2.55 mem_delta=+7MB wall=59.5s
- seed 5: fps=56.07 fps/actor=2.95 mem_delta=+6MB wall=59.6s

### N=20

**python_mp** (n=5)
- seed 1: fps=43.13 fps/actor=2.16 mem_delta=+7MB wall=61.6s
- seed 2: fps=49.26 fps/actor=2.46 mem_delta=+6MB wall=61.5s
- seed 3: fps=46.33 fps/actor=2.32 mem_delta=+7MB wall=61.7s
- seed 4: fps=49.86 fps/actor=2.49 mem_delta=+7MB wall=61.7s
- seed 5: fps=56.06 fps/actor=2.80 mem_delta=+7MB wall=61.7s

### N=22

**python_mp** (n=5)
- seed 1: fps=49.60 fps/actor=2.25 mem_delta=+7MB wall=66.4s
- seed 2: fps=46.73 fps/actor=2.12 mem_delta=+6MB wall=65.9s
- seed 3: fps=47.73 fps/actor=2.17 mem_delta=+6MB wall=65.9s
- seed 4: fps=50.46 fps/actor=2.29 mem_delta=+6MB wall=65.9s
- seed 5: fps=48.53 fps/actor=2.21 mem_delta=+6MB wall=65.9s
