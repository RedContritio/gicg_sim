# I29 Win box fair bench — pure collector throughput

Commit: `660fc3d`
Date: 2026-05-26 07:57
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|----------|---------|---------------------|---------------------------|----------------|--------|
| 4 | go | 39.79 ± 0.00 (0%) | 9.95 ± 0.00 (0%) | +10 MB | 1 |
| 4 | python_mp | 16.47 ± 0.00 (0%) | 4.12 ± 0.00 (0%) | +6 MB | 1 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 4 | 2.42x | Go faster |

## Per-seed detail

### N=4

**go** (n=1)
- seed 1: fps=39.79 fps/actor=9.95 mem_delta=+10MB wall=20.7s

**python_mp** (n=1)
- seed 1: fps=16.47 fps/actor=4.12 mem_delta=+6MB wall=28.2s
