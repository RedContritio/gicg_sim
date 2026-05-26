# I29 T-C2 Win N=16 bench + root cause audit (2026-05-24)

## Bench 数据(FINAL,Go-actor 完成 1846 s wall)

| Metric | Python mp | Go-actor | Ratio (Go/Py) |
|--------|----------:|---------:|--------------:|
| fps (steady) | 40.14 | 26.9 | 0.67x (Go 1.5x slower) |
| **eps/s** | 1.845 | **1.901** | **1.03x (Go 3% faster!)** |
| frames/episode | 21.76 | 14.15 | (paradigm 实现差,见下) |
| master_rss_mb max | 3812 | 4711 | 1.24x (Go +24%) |
| batching_efficiency | 0.888 | (Go path 未 instrument) | - |
| batch_size_avg | 14.2 | - | - |
| forward_ms_avg | 12.56 ms | - | - |

**关键 insight**: Go-actor **每秒完成更多游戏 (1.901 > 1.845 eps/s)**,但每个 episode 推
更少 transition (14 vs 21)。 frames/episode 差异不是 perf 问题,是 paradigm 实现:
Python mp 可能 log 双方 turn 或 marker transition 计入 frames,Go-actor 只 log me-turn。

但 fps_per_actor 是 training 数据率(transitions/s):Go 26.9 vs Python 40.14 → Python
training 数据率 1.5x。 若 fix per-transition push 瓶颈(F1),Go eps/s 优势能转化为 fps 优势。

| Platform | N | Python mp fps/actor | Go-actor fps/actor | Ratio |
|----------|---|--------------------:|-------------------:|------:|
| Mac | 4 | 48.1 | 12.7 | 3.8x worse |
| Win | 16 | 2.51 | ~1.7 | 1.5x worse |

Win 比 Mac 缩小一半(3.8x → 1.5x),与「Win training overhead 隐藏 collect overhead 部分」hypothesis 吻合。

## T-B1 mutex_wait fix verified

Go perf trace (Win Go-actor bench in-flight,wall_s=446):
- `transition_writer.mutex_wait` mean = **0.0 ms** ✓ (T-B1 worked)
- `transition_writer.encode` mean = 0.0 ms (instantaneous)
- `transition_writer.socket_write` mean = **693 ms/call** (TCP backpressure)
- `transition_writer.push` mean = 737 ms/call (basically all socket_write)
- `inference_client.recv` mean = 54 ms/call (~socket RTT + InfServer batching + GPU)
- `inference_client.send` mean = 0.4 ms/call (fast)
- `trans_queue qsize` = **4096 = maxsize** 全程饱和

## Python-side perf data

`assembler.ingest` (per call,driver thread):
- mean = 0.12 ms — VERY FAST
- p95 = 0.7 ms

`pipeline.loss_compute`: mean = **46 ms × 8/s = 368 ms/s wall** (training 占 driver 50% wall)

## Root cause(3 因子,ranked by impact)

### 1. Per-transition push granularity(主因)

| Path | per episode push 数 | drain ops 数 | Driver work scale |
|------|---------------------|--------------|-------------------|
| Python mp | 1 (episode-level via SHMRing) | 1 try_pop + 1 pickle.loads | 1x |
| Go-actor | **12** (~11 me-turns + 1 marker) | 12 q.get + 12 assembler.ingest | **12x** |

Go-actor 每 episode 推 12 条 transition,Python mp 推 1 个 episode blob。 driver 主线程 collect 调 `assembler.ingest` 12x 比 Python mp 多。

### 2. TCP socket inference RTT vs mp.Queue

Go-actor inference 路径多了 TCP framing + syscall + socket listener handler thread,vs Python mp 的 mp.Queue OS pipe — ~1-2 ms/call 额外 latency × 11 me-turns/episode × 16 actors = ~200-350 ms/s 额外 latency。

### 3. Win vs Mac 差距解释

Win GPU training 46ms × 8/s = 368ms/s wall → driver 主线程 ~37% training。Go-actor 多出来的 collect overhead 在 training 期间被 queue 缓冲。

Mac CPU training 快,collect 占 wall 比例更高 → Go-actor overhead 完全暴露 → 3.8x gap 比 Win 1.5x 大。

## Fix paths(候选,详 deep audit)

| F# | 做法 | LOC | Risk | Win 预期 fps | Mac 预期 fps/actor | 是否 close gap |
|----|------|-----|------|--------------|---------------------|----------------|
| F1 | Episode-granularity push(Go buffer episode 末一次性 push) | ~200 | LOW-MED | 35-38(35→Py 40 接近) | 25-35(vs Py 48) | Mac 部分 close |
| F2 | SHMRing 替换 TCP(cross-language shm) | ~500+ | HIGH | 35-40 | 35-40 | 接近 close |
| F3 | Drainer thread 解耦 collector | ~80 | HIGH(GIL) | +5-10 fps | 微 | 不能 close |
| F4 | Go 侧 episode buffer 不改 wire | ~100 | LOW | 30-33 | 微 | 不能 close |
| F5 | Inference 改 mp.Queue(Route B) | ~300+ | HIGH(cgo) | TBD | TBD | 风险大于收益 |

## 推荐: F1 — Episode-granularity push

LOC 中等,风险可控,root cause 直接 fix。 与 user 路线 framework 对应:
- 介于路线 A (SHMRing) 和 plan 原本之间,**最值得先做**
- 失败 / 不够 → 再做 F2 SHMRing

设计要点:
- Go 侧 `runEpisode` 用 `[]DmcTransitionPayload` slice buffer 整 episode
- Episode done 时序列化为新 wire type `episode_v1`(含 episode payloads 数组 + done marker)
- 一次 TCP write 推 episode-level message(~12 transitions × 12KB = ~144KB)
- Python `assembler.ingest_episode(payloads)` 路径,内部复用 `_try_assemble`
- 新旧 wire type 共存,单测对比

## 决策

走 F1。 在 **新 branch `feature/i29-go-actor-episode-push`** 实现(per user 2026-05-24 「每路线从当前 commit 起新 branch」指示)。
