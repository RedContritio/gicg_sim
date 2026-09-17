# I29 Win box fair bench — pure collector throughput

Commit: `063489d`
Date: 2026-05-26 08:41
Box: dev@192.0.2.10 (DEV-PC, 5070 Ti + 9950X3D)
Window: 15s per run

## Headline summary

| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|------|---------|---------------------|---------------------------|----------------|--------|
| N=4 | go | 28.99 ± 0.00 (0%) | 7.25 ± 0.00 (0%) | +3 MB | 1 |
| N=4 | python_mp | 16.33 ± 0.00 (0%) | 4.08 ± 0.00 (0%) | +6 MB | 1 |
| N=8 | go | 19.13 ± 0.00 (0%) | 2.39 ± 0.00 (0%) | +2 MB | 1 |
| N=8 | python_mp | 29.07 ± 0.00 (0%) | 3.63 ± 0.00 (0%) | +7 MB | 1 |
| N=16 | go | 69.11 ± 0.00 (0%) | 4.32 ± 0.00 (0%) | +25 MB | 1 |
| N=16 | python_mp | 50.13 ± 0.00 (0%) | 3.13 ± 0.00 (0%) | +7 MB | 1 |
| N=24 | go | 28.26 ± 0.00 (0%) | 1.18 ± 0.00 (0%) | +25 MB | 1 |
| N=24 | python_mp | 20.73 ± 0.00 (0%) | 0.86 ± 0.00 (0%) | +7 MB | 1 |
| N=32 | go | 61.12 ± 0.00 (0%) | 1.91 ± 0.00 (0%) | +25 MB | 1 |
| N=32 | python_mp | 21.27 ± 0.00 (0%) | 0.66 ± 0.00 (0%) | +6 MB | 1 |

## Ratio (Go / Python mp)

| Cell | fps/actor ratio | Interpretation |
|------|----------------|----------------|
| N=4 | 1.78x | Go faster |
| N=8 | 0.66x | Python mp faster |
| N=16 | 1.38x | Go faster |
| N=24 | 1.37x | Go faster |
| N=32 | 2.89x | Go faster |

## Per-seed detail

### N=4

**go** (n=1)
- seed 1: fps=28.99 fps/actor=7.25 mem_delta=+3MB wall=20.2s

**python_mp** (n=1)
- seed 1: fps=16.33 fps/actor=4.08 mem_delta=+6MB wall=28.2s

### N=8

**go** (n=1)
- seed 1: fps=19.13 fps/actor=2.39 mem_delta=+2MB wall=20.4s

**python_mp** (n=1)
- seed 1: fps=29.07 fps/actor=3.63 mem_delta=+7MB wall=36.5s

### N=16

**go** (n=1)
- seed 1: fps=69.11 fps/actor=4.32 mem_delta=+25MB wall=20.6s

**python_mp** (n=1)
- seed 1: fps=50.13 fps/actor=3.13 mem_delta=+7MB wall=53.3s

### N=24

**go** (n=1)
- seed 1: fps=28.26 fps/actor=1.18 mem_delta=+25MB wall=20.8s

**python_mp** (n=1)
- seed 1: fps=20.73 fps/actor=0.86 mem_delta=+7MB wall=70.1s

### N=32

**go** (n=1)
- seed 1: fps=61.12 fps/actor=1.91 mem_delta=+25MB wall=25.9s

**python_mp** (n=1)
- seed 1: fps=21.27 fps/actor=0.66 mem_delta=+6MB wall=87.0s
