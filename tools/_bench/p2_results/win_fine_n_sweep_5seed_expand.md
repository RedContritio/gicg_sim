# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 10:32
Box: dev@192.0.2.10 (DEV-PC, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=16 | go | 50.35 ± 14.73 (29%) | 3.15 ± 0.92 (29%) | +21 MB | 5 |
| N=19 | go | 63.14 ± 3.68 (6%) | 3.32 ± 0.19 (6%) | +25 MB | 5 |
| N=20 | go | 52.37 ± 15.59 (30%) | 2.62 ± 0.78 (30%) | +24 MB | 5 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=16 | N/A | insufficient data |
| N=19 | N/A | insufficient data |
| N=20 | N/A | insufficient data |

## Per-seed detail

### N=16

**go** (n=5)
- seed 1: fps=61.93 fps/actor=3.87 mem_delta=+26MB wall=20.6s
- seed 2: fps=42.26 fps/actor=2.64 mem_delta=+14MB wall=20.7s
- seed 3: fps=58.31 fps/actor=3.64 mem_delta=+21MB wall=20.6s
- seed 4: fps=28.20 fps/actor=1.76 mem_delta=+20MB wall=20.7s
- seed 5: fps=61.05 fps/actor=3.82 mem_delta=+22MB wall=25.3s

### N=19

**go** (n=5)
- seed 1: fps=64.86 fps/actor=3.41 mem_delta=+26MB wall=25.4s
- seed 2: fps=61.67 fps/actor=3.25 mem_delta=+24MB wall=25.4s
- seed 3: fps=57.45 fps/actor=3.02 mem_delta=+21MB wall=20.8s
- seed 4: fps=66.85 fps/actor=3.52 mem_delta=+24MB wall=20.7s
- seed 5: fps=64.85 fps/actor=3.41 mem_delta=+28MB wall=25.4s

### N=20

**go** (n=5)
- seed 1: fps=63.51 fps/actor=3.18 mem_delta=+25MB wall=20.7s
- seed 2: fps=62.26 fps/actor=3.11 mem_delta=+24MB wall=25.4s
- seed 3: fps=25.99 fps/actor=1.30 mem_delta=+23MB wall=20.8s
- seed 4: fps=50.59 fps/actor=2.53 mem_delta=+21MB wall=20.7s
- seed 5: fps=59.52 fps/actor=2.98 mem_delta=+27MB wall=25.5s
