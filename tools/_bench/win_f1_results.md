# I29 T-C2 Win N=16 fair bench results

Date: $(date)

Python mp dir: `202605240056_000114_bench_v_legacy_python_mp`
Go-actor dir: `202605240901_000116_bench_v_legacy_go`

## Headline

| Metric | Python mp | Go-actor | Ratio (Go/Py) |
|--------|----------:|---------:|--------------:|
| fps (steady) | 40.14 | 26.15 | 0.65x |
| eps/s | 1.845 | 1.835 | 0.99x |
| master_rss_mb max | 3812.0 | 9680.0 | 2.54x |
| batching_efficiency mean | 0.888 | - | - |
| batch_size_avg mean | 14.2 | - | - |
| forward_ms_avg mean | 12.56 | - | - |

## Go-actor sub-span timing (Go-actor only)

| Stage | n calls | mean_ms | max_ms |
|---|--:|--:|--:|
| `dmc.build_infer_request` | 36011 | 0.114 | 8.081 |
| `dmc.build_static_obs` | 2517 | 0.169 | 4.505 |
| `dmc.engine_step` | 74919 | 0.071 | 9.954 |
| `dmc.episode` | 2520 | 5535.741 | 15707.030 |
| `dmc.opp_f1d2_select` | 13039 | 14.099 | 254.620 |
| `dmc.opp_f1d4_select` | 6498 | 339.943 | 875.071 |
| `dmc.opp_minimax_select` | 19537 | 122.474 | 875.071 |
| `dmc.opp_random` | 7555 | 0.000 | 0.000 |
| `game.deepcopy` | 22612703 | 0.024 | 17.027 |
| `inference_client.decode` | 47835 | 0.026 | 9.954 |
| `inference_client.encode` | 47876 | 0.036 | 10.385 |
| `inference_client.recv` | 47835 | 63.849 | 226.741 |
| `inference_client.request` | 35979 | 65.009 | 227.747 |
| `inference_client.send` | 47880 | 0.505 | 14.780 |
| `transition_writer.encode` | 2568 | 0.272 | 6.020 |
| `transition_writer.mutex_wait` | 2568 | 0.000 | 0.000 |
| `transition_writer.push` | 2520 | 3234.714 | 14795.490 |
| `transition_writer.socket_write` | 2520 | 3234.434 | 14795.490 |

注:观察 transition_writer.mutex_wait 是否 ≈ 0 (T-B1 fix 验证)。
观察 inference_client.recv 大小 - send 时间差 ≈ InfServer batching window + GPU forward。

## Go-actor backpressure

- _trans_queue.qsize max = 4096 / mean = 3089.8
- alive_count unique = [0, 8, 16]
