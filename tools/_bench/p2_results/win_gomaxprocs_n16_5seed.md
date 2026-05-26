# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 10:15
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=16 G=1 | go | 52.54 ± 17.86 (34%) | 3.28 ± 1.12 (34%) | +21 MB | 5 |
| N=16 G=2 | go | 53.51 ± 18.02 (34%) | 3.34 ± 1.13 (34%) | +23 MB | 5 |
| N=16 G=4 | go | 50.08 ± 9.86 (20%) | 3.13 ± 0.62 (20%) | +22 MB | 5 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=16 G=1 | N/A | insufficient data |
| N=16 G=2 | N/A | insufficient data |
| N=16 G=4 | N/A | insufficient data |

## Per-seed detail

### N=16 G=1

**go** (n=5)
- seed 1: fps=67.73 fps/actor=4.23 mem_delta=+25MB wall=20.7s
- seed 2: fps=65.38 fps/actor=4.09 mem_delta=+25MB wall=20.7s
- seed 3: fps=51.39 fps/actor=3.21 mem_delta=+17MB wall=20.7s
- seed 4: fps=55.19 fps/actor=3.45 mem_delta=+23MB wall=20.6s
- seed 5: fps=23.00 fps/actor=1.44 mem_delta=+15MB wall=20.7s

### N=16 G=2

**go** (n=5)
- seed 1: fps=57.53 fps/actor=3.60 mem_delta=+25MB wall=20.8s
- seed 2: fps=53.32 fps/actor=3.33 mem_delta=+18MB wall=20.6s
- seed 3: fps=23.40 fps/actor=1.46 mem_delta=+19MB wall=20.6s
- seed 4: fps=70.52 fps/actor=4.41 mem_delta=+27MB wall=25.4s
- seed 5: fps=62.79 fps/actor=3.92 mem_delta=+25MB wall=20.8s

### N=16 G=4

**go** (n=5)
- seed 1: fps=53.32 fps/actor=3.33 mem_delta=+22MB wall=20.6s
- seed 2: fps=37.99 fps/actor=2.37 mem_delta=+12MB wall=20.7s
- seed 3: fps=43.40 fps/actor=2.71 mem_delta=+28MB wall=20.7s
- seed 4: fps=63.64 fps/actor=3.98 mem_delta=+25MB wall=20.7s
- seed 5: fps=52.06 fps/actor=3.25 mem_delta=+24MB wall=20.7s
