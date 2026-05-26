# I29 T-C1 Mac fair bench — pure collector throughput

Commit: `4a9d213`  
Date: 2026-05-26 01:21  
Window: 15s per run (same as Go-actor test)  

## Headline summary

| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |
|----------|---------|---------------------|---------------------------|----------------|--------|
| 2 | go | 5.76 ± 2.42 (42%) | 2.88 ± 1.21 (42%) | +8 MB | 5 |
| 2 | python_mp | 6.20 ± 3.80 (61%) | 3.10 ± 1.90 (61%) | +39 MB | 5 |
| 8 | go | 7.73 ± 0.00 (0%) | 0.97 ± 0.00 (0%) | +19 MB | 1 |
| 8 | python_mp | 34.84 ± 14.22 (41%) | 4.35 ± 1.78 (41%) | +41 MB | 5 |

## Ratio (Go / Python mp)

| N actors | fps/actor ratio | Interpretation |
|----------|----------------|----------------|
| 2 | 0.93x | Python mp faster |
| 8 | 0.22x | Python mp faster |

## Per-seed detail

### N=2

**go** (n=5)
- seed 1: fps=5.60 fps/actor=2.80 mem_delta=+7MB wall=19.1s
- seed 2: fps=6.33 fps/actor=3.17 mem_delta=+10MB wall=18.1s
- seed 3: fps=9.53 fps/actor=4.77 mem_delta=+8MB wall=20.5s
- seed 4: fps=3.93 fps/actor=1.97 mem_delta=+9MB wall=17.3s
- seed 5: fps=3.40 fps/actor=1.70 mem_delta=+5MB wall=20.4s

**python_mp** (n=5)
- seed 1: fps=3.93 fps/actor=1.97 mem_delta=+39MB wall=21.1s
- seed 2: fps=11.07 fps/actor=5.53 mem_delta=+39MB wall=21.1s
- seed 3: fps=2.53 fps/actor=1.27 mem_delta=+39MB wall=21.1s
- seed 4: fps=9.47 fps/actor=4.73 mem_delta=+40MB wall=21.1s
- seed 5: fps=4.00 fps/actor=2.00 mem_delta=+39MB wall=21.1s

### N=8

**go** (n=1)
- seed 1: fps=7.73 fps/actor=0.97 mem_delta=+19MB wall=17.8s

**python_mp** (n=5)
- seed 1: fps=30.40 fps/actor=3.80 mem_delta=+42MB wall=33.4s
- seed 2: fps=27.53 fps/actor=3.44 mem_delta=+41MB wall=33.4s
- seed 3: fps=27.86 fps/actor=3.48 mem_delta=+41MB wall=33.4s
- seed 4: fps=28.20 fps/actor=3.52 mem_delta=+41MB wall=33.5s
- seed 5: fps=60.20 fps/actor=7.52 mem_delta=+42MB wall=33.4s
