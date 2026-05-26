# I29 T-C2 Win N=16 fair bench results

Date: $(date)

Python mp dir: `202605240056_000114_bench_v_legacy_python_mp`
Go-actor dir: `202605240122_000115_bench_v_legacy_go`

## Headline

| Metric | Python mp | Go-actor | Ratio (Go/Py) |
|--------|----------:|---------:|--------------:|
| fps (steady) | 40.14 | 26.9 | 0.67x |
| eps/s | 1.845 | 1.901 | 1.03x |
| master_rss_mb max | 3812.0 | 4711.0 | 1.24x |
| batching_efficiency mean | 0.888 | - | - |
| batch_size_avg mean | 14.2 | - | - |
| forward_ms_avg mean | 12.56 | - | - |

## Go-actor sub-span timing (Go-actor only)

| Stage | n calls | mean_ms | max_ms |
|---|--:|--:|--:|
| `dmc.build_infer_request` | 34073 | 0.090 | 6.587 |
| `dmc.build_static_obs` | 2451 | 0.154 | 4.509 |
| `dmc.engine_step` | 71658 | 0.052 | 7.028 |
| `dmc.episode` | 2450 | 8181.516 | 21943.039 |
| `dmc.opp_f1d2_select` | 12361 | 11.584 | 207.577 |
| `dmc.opp_f1d4_select` | 6699 | 279.597 | 743.986 |
| `dmc.opp_minimax_select` | 19060 | 105.782 | 743.986 |
| `dmc.opp_random` | 7433 | 0.000 | 0.000 |
| `game.deepcopy` | 21280720 | 0.022 | 17.436 |
| `inference_client.decode` | 45164 | 0.021 | 1.943 |
| `inference_client.encode` | 45195 | 0.029 | 8.018 |
| `inference_client.recv` | 45162 | 56.783 | 198.956 |
| `inference_client.request` | 34022 | 57.995 | 199.964 |
| `inference_client.send` | 45192 | 0.442 | 14.449 |
| `transition_writer.encode` | 36473 | 0.013 | 4.005 |
| `transition_writer.mutex_wait` | 36472 | 0.000 | 1.009 |
| `transition_writer.push` | 33857 | 434.365 | 16683.992 |
| `transition_writer.socket_write` | 36307 | 405.069 | 16683.992 |

注:观察 transition_writer.mutex_wait 是否 ≈ 0 (T-B1 fix 验证)。
观察 inference_client.recv 大小 - send 时间差 ≈ InfServer batching window + GPU forward。

## Go-actor backpressure

- _trans_queue.qsize max = 4096 / mean = 4026.5
- alive_count unique = [0, 16]
