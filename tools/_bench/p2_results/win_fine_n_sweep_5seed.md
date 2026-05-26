# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 10:25
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=14 | go | 47.43 ± 15.10 (32%) | 3.39 ± 1.08 (32%) | +19 MB | 5 |
| N=15 | go | 49.05 ± 16.18 (33%) | 3.27 ± 1.08 (33%) | +21 MB | 5 |
| N=16 | go | 37.42 ± 19.27 (52%) | 2.34 ± 1.20 (52%) | +19 MB | 5 |
| N=17 | go | 56.36 ± 10.58 (19%) | 3.31 ± 0.62 (19%) | +24 MB | 5 |
| N=18 | go | 56.89 ± 8.49 (15%) | 3.16 ± 0.47 (15%) | +22 MB | 5 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=14 | N/A | insufficient data |
| N=15 | N/A | insufficient data |
| N=16 | N/A | insufficient data |
| N=17 | N/A | insufficient data |
| N=18 | N/A | insufficient data |

## Per-seed detail

### N=14

**go** (n=5)
- seed 1: fps=62.33 fps/actor=4.45 mem_delta=+25MB wall=20.6s
- seed 2: fps=41.72 fps/actor=2.98 mem_delta=+13MB wall=20.7s
- seed 3: fps=49.66 fps/actor=3.55 mem_delta=+20MB wall=20.5s
- seed 4: fps=24.59 fps/actor=1.76 mem_delta=+17MB wall=20.6s
- seed 5: fps=58.85 fps/actor=4.20 mem_delta=+21MB wall=20.6s

### N=15

**go** (n=5)
- seed 1: fps=42.79 fps/actor=2.85 mem_delta=+16MB wall=20.6s
- seed 2: fps=54.65 fps/actor=3.64 mem_delta=+26MB wall=20.6s
- seed 3: fps=26.46 fps/actor=1.76 mem_delta=+13MB wall=20.6s
- seed 4: fps=70.57 fps/actor=4.70 mem_delta=+28MB wall=25.3s
- seed 5: fps=50.79 fps/actor=3.39 mem_delta=+20MB wall=20.6s

### N=16

**go** (n=5)
- seed 1: fps=20.60 fps/actor=1.29 mem_delta=+13MB wall=20.7s
- seed 2: fps=27.33 fps/actor=1.71 mem_delta=+21MB wall=20.7s
- seed 3: fps=54.71 fps/actor=3.42 mem_delta=+23MB wall=20.7s
- seed 4: fps=61.66 fps/actor=3.85 mem_delta=+22MB wall=20.6s
- seed 5: fps=22.80 fps/actor=1.42 mem_delta=+16MB wall=20.8s

### N=17

**go** (n=5)
- seed 1: fps=65.53 fps/actor=3.85 mem_delta=+27MB wall=25.4s
- seed 2: fps=42.33 fps/actor=2.49 mem_delta=+22MB wall=20.7s
- seed 3: fps=64.84 fps/actor=3.81 mem_delta=+25MB wall=25.4s
- seed 4: fps=61.20 fps/actor=3.60 mem_delta=+25MB wall=20.7s
- seed 5: fps=47.92 fps/actor=2.82 mem_delta=+22MB wall=20.7s

### N=18

**go** (n=5)
- seed 1: fps=57.26 fps/actor=3.18 mem_delta=+22MB wall=20.7s
- seed 2: fps=64.99 fps/actor=3.61 mem_delta=+24MB wall=20.8s
- seed 3: fps=56.39 fps/actor=3.13 mem_delta=+25MB wall=20.8s
- seed 4: fps=62.66 fps/actor=3.48 mem_delta=+24MB wall=20.8s
- seed 5: fps=43.13 fps/actor=2.40 mem_delta=+17MB wall=20.8s
