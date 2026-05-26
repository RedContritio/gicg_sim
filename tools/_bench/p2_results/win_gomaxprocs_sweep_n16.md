# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 10:08
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=16 G=1 | go | 36.64 ± 8.32 (23%) | 2.29 ± 0.52 (23%) | +16 MB | 3 |
| N=16 G=2 | go | 57.87 ± 10.81 (19%) | 3.62 ± 0.67 (19%) | +22 MB | 3 |
| N=16 G=4 | go | 43.41 ± 20.99 (48%) | 2.72 ± 1.31 (48%) | +20 MB | 3 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=16 G=1 | N/A | insufficient data |
| N=16 G=2 | N/A | insufficient data |
| N=16 G=4 | N/A | insufficient data |

## Per-seed detail

### N=16 G=1

**go** (n=3)
- seed 1: fps=29.39 fps/actor=1.84 mem_delta=+7MB wall=20.6s
- seed 2: fps=45.73 fps/actor=2.86 mem_delta=+22MB wall=20.6s
- seed 3: fps=34.80 fps/actor=2.17 mem_delta=+19MB wall=20.7s

### N=16 G=2

**go** (n=3)
- seed 1: fps=45.39 fps/actor=2.84 mem_delta=+19MB wall=20.7s
- seed 2: fps=64.04 fps/actor=4.00 mem_delta=+24MB wall=20.7s
- seed 3: fps=64.19 fps/actor=4.01 mem_delta=+24MB wall=25.3s

### N=16 G=4

**go** (n=3)
- seed 1: fps=65.05 fps/actor=4.07 mem_delta=+26MB wall=20.6s
- seed 2: fps=42.05 fps/actor=2.63 mem_delta=+15MB wall=20.7s
- seed 3: fps=23.13 fps/actor=1.45 mem_delta=+18MB wall=20.6s
