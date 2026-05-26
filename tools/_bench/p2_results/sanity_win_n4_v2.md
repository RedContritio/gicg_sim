# I29 Win box fair bench — pure collector throughput

Commit: `a6c2942`
Date: 2026-05-26 08:15
Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=4 | go | 11.46 ± 0.00 (0%) | 2.87 ± 0.00 (0%) | -4 MB | 1 |
| N=4 | python_mp | 16.80 ± 0.00 (0%) | 4.20 ± 0.00 (0%) | +6 MB | 1 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=4 | 0.68x | Python mp faster |

## Per-seed detail

### N=4

**go** (n=1)
- seed 1: fps=11.46 fps/actor=2.87 mem_delta=-4MB wall=20.2s

**python_mp** (n=1)
- seed 1: fps=16.80 fps/actor=4.20 mem_delta=+6MB wall=28.1s
