# I29 Win box fair bench — pure collector throughput

Commit: `c07bbec`
Date: 2026-05-26 10:40
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=19 T=15s | go | 49.90 ± 21.31 (43%) | 2.63 ± 1.12 (43%) | +23 MB | 3 |
| N=19 T=30s | go | 42.59 ± 9.39 (22%) | 2.24 ± 0.49 (22%) | +37 MB | 3 |
| N=19 T=60s | go | 13.40 ± 7.41 (55%) | 0.70 ± 0.39 (56%) | +32 MB | 3 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=19 T=15s | N/A | insufficient data |
| N=19 T=30s | N/A | insufficient data |
| N=19 T=60s | N/A | insufficient data |

## Per-seed detail

### N=19 T=15s

**go** (n=3)
- seed 1: fps=67.79 fps/actor=3.57 mem_delta=+26MB wall=20.7s
- seed 2: fps=55.59 fps/actor=2.93 mem_delta=+29MB wall=25.4s
- seed 3: fps=26.33 fps/actor=1.39 mem_delta=+14MB wall=20.8s

### N=19 T=30s

**go** (n=3)
- seed 1: fps=53.10 fps/actor=2.79 mem_delta=+46MB wall=35.8s
- seed 2: fps=35.03 fps/actor=1.84 mem_delta=+29MB wall=35.9s
- seed 3: fps=39.63 fps/actor=2.09 mem_delta=+36MB wall=35.9s

### N=19 T=60s

**go** (n=3)
- seed 1: fps=11.80 fps/actor=0.62 mem_delta=+25MB wall=65.9s
- seed 2: fps=21.48 fps/actor=1.13 mem_delta=+46MB wall=66.0s
- seed 3: fps=6.92 fps/actor=0.36 mem_delta=+25MB wall=65.9s
