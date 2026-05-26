# I29 T-C2 Win N=16 fair bench results

Date: $(date)

Python mp dir: `202605240056_000114_bench_v_legacy_python_mp`
Go-actor dir: `202605241436_000117_bench_v_legacy_go`

## Headline

| Metric | Python mp | Go-actor | Ratio (Go/Py) |
|--------|----------:|---------:|--------------:|
| fps (steady) | 40.14 | 22.68 | 0.57x |
| eps/s | 1.845 | 1.667 | 0.90x |
| master_rss_mb max | 3812.0 | 10511.0 | 2.76x |
| batching_efficiency mean | 0.888 | - | - |
| batch_size_avg mean | 14.2 | - | - |
| forward_ms_avg mean | 12.56 | - | - |

## Go-actor sub-span timing (Go-actor only)

| Stage | n calls | mean_ms | max_ms |
|---|--:|--:|--:|
| `dmc.build_infer_request` | 35075 | 0.122 | 15.411 |
| `dmc.build_static_obs` | 2512 | 0.240 | 10.681 |
| `dmc.engine_step` | 76554 | 0.070 | 15.698 |
| `dmc.episode` | 2515 | 6139.881 | 58164.243 |
| `dmc.opp_f1d2_select` | 13825 | 16.787 | 346.748 |
| `dmc.opp_f1d4_select` | 7219 | 396.861 | 925.469 |
| `dmc.opp_minimax_select` | 21044 | 147.168 | 925.469 |
| `dmc.opp_random` | 8128 | 0.000 | 1.520 |
| `game.deepcopy` | 26754110 | 0.025 | 20.304 |
| `inference_client.decode` | 47383 | 0.014 | 11.785 |
| `inference_client.encode` | 47367 | 0.042 | 15.861 |
| `inference_client.recv` | 47384 | 58.352 | 209.726 |
| `inference_client.request` | 35097 | 58.752 | 209.726 |
| `inference_client.send` | 47367 | 0.035 | 15.813 |
| `transition_writer.encode` | 2584 | 0.278 | 12.039 |
| `transition_writer.mutex_wait` | 2584 | 0.000 | 0.000 |
| `transition_writer.push` | 2515 | 3763.405 | 57259.732 |
| `transition_writer.socket_write` | 2515 | 3763.116 | 57259.732 |

注:观察 transition_writer.mutex_wait 是否 ≈ 0 (T-B1 fix 验证)。
观察 inference_client.recv 大小 - send 时间差 ≈ InfServer batching window + GPU forward。

## Go-actor backpressure

- _trans_queue.qsize max = 4096 / mean = 3125.0
- alive_count unique = [0, 16]
