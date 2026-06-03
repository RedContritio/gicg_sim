# I29 Go runtime perf optimization plan

Branch: `feature/i29-go-actor-pool`(post 2026-05-24 merge to main + 新分支)

## 目标(session goal,2026-05-24)

Go runtime 性能 **显著优于** Python 多进程版本,**接近理论性能极限**,所有不符部分有可信解释。最终
完全替代 Python 方案,Mac + Win 双平台都 ≥ Python baseline。

工作流约束:**多设计少运行**。比起 5 次「添加指标 → 跑 Win」循环,5 次添加指标 + 1 次跑 Win 是更好做法。
Win 跑是 expensive,Mac smoke + 代码 review 是 cheap。

## 理论性能模型(audit 数据,2026-05-24)

### 单 transition 端到端 stage breakdown(Win N=16, 5070 Ti, d_model=128)

| Stage | Side | Mean cost | 注释 |
|-------|------|-----------|------|
| obs_encode | Actor (Go) | ~2 ms | dyn_obs cast + refs/pay layout |
| inference_client.request | Actor (Go) | ~50 ms | socket RPC round-trip |
| opp_select(avg over mix) | Actor (Go) | ~200 ms | f1d2 185 / f1d4 479 / random ~0 |
| engine_step | Actor (Go) | ~5-10 ms | go-native game.Step() |
| transition_writer.push | Actor (Go) | **146 ms** | conc 7.42(单 mutex 序列化 N=16) |
| listener.recv + decode | Driver (Py) | ~5 ms est | 未 instrument |
| assembler.ingest | Driver (Py) | ~3-5 ms est | numpy reshape,未 instrument |
| inf_server forward(b16) | GPU | 10 ms 实测 / 5 ms 理论 | batching_efficiency 5.5% |

### 理论上限

| 组件 | 上限 trans/s | 注释 |
|------|------------|------|
| Per-actor (N=1, serial) | ~5 trans/s | sum(actor side) ≈ 207 ms |
| N=16 actor 并发(无 contention) | **~77 trans/s** | 16 / 0.207 = naive linear |
| transition_writer.push mutex | **6.8 trans/s** | 当前实际瓶颈 |
| InfServer GPU forward 理论 | 3200 req/s | d128 batch16 5 ms |
| InfServer GPU 实际(5.5% eff) | 176 req/s | batch_avg 1.6 |
| Socket TCP localhost | >1000 trans/s | 非瓶颈 |

**当前 Win N=16 实测**:1.92 trans/s(25.2 fps / 13.1 frames-per-ep)= 理论上限的 **2.8%**,push-limited 上限的 **28%**。

**Python mp 实测**:35-37 fps total = 2.2 trans/s per-actor。Go 当前 1.92 < Python 2.2,**架构上的根因 = Python 走 InfClient centralized batching(batch 8-12),Go 走 per-actor socket(batch 1-2)**。

### 目标(acceptance gate)

| 平台 | 配置 | Python baseline | Go goal | 倍率 |
|------|------|----------------|---------|------|
| Win | N=16 | 35-37 fps | **≥ 70 fps** | 2x |
| Mac | N=4 | ~30 fps | **≥ 45 fps** | 1.5x |
| Mac | N=8 | (run 待补) | **≥ Python N=8** | ≥1x |

理由:Win N=16 70 fps = 5.3 trans/s = push 上限 78%(假设 push mutex 解决后达 naive linear 70%);Mac CPU
小,scaling 自然弱,1.5x 即可。

## 工作流(3 Phase)

### Phase A — Observability + 直接 fix(~80 LOC, Mac smoke 可验)

5 个独立任务,可并行。完成后 Mac smoke 验 instrumentation 都活,无 regression。

| T# | 改动 | 文件 | LOC | 嫌疑 H# |
|----|------|------|-----|---------|
| T-A1 | `TransitionWriter` 加 `SetNoDelay(true)` | gicg_actor/transition_writer.go | 3 | H3 Nagle |
| T-A2 | `Push()` 拆 3 sub-span(encode / mutex_wait / socket_write) | 同上 | 10 | H4 mutex / H5 breakdown |
| T-A3 | `InferenceClient.Request` 拆 sub-span(encode / write / read / decode) | gicg_actor/inference_client.go | 8 | inference 56 ms 拆解 |
| T-A4 | `assembler.ingest` 加 perf_trace span | training/paradigms/dmc/go_collector.py:88 + _go_assembler.py | 5 | H2 |
| T-A5 | `_trans_queue.qsize()` + `AliveCount` 周期 sampler | training/core/logging.py + go_collector.py | 25 | H1 + actor 死亡可见性 |

### Phase B — 架构 fix(~250 LOC, Mac smoke 可验)

依赖 Phase A 数据**确认**根因后才动。预期数据:Phase A 收完后 T-A2 sub-span 会显示 mutex_wait
占 push 大头(>50%)→ Phase B 必做。

| T# | 改动 | 文件 | LOC | 改什么 |
|----|------|------|-----|--------|
| T-B1 | `TransitionWriter` per-actor conn(去单 mutex) | gicg_actor/transition_writer.go + pool.go | ~60 | 同 T-RR.5 cluster-2 inference 思路:N 条 conn |
| T-B2 | InfServer Go-side batch coalescer(短 timeout 攒 batch) | gicg_actor/inference_client.go + InfServer | ~150 | 把 batch_avg 1.6 拉到 8-12,匹配 Python baseline |
| T-B3 | Python listener thread `recv → decode → enqueue` instrument + 性能 audit | training/core/actor/transition_sink_listener.py | ~30 | T-A 暴露 driver 慢则补 |

T-B2 是大头,可能拆 sub-task(Go 端 client-side coalescer vs Python InfServer-side adaptive batching)。具体设计
在 Phase A 完后定。

### Phase C — Bench + 决策(轻量)

| T# | 动作 | 平台 | 说明 |
|----|------|------|------|
| T-C1 | Mac N=4 + N=8 fair bench(Python mp vs Go-actor 各 1 run) | Mac | 50K frames 各,串行,同 commit |
| T-C2 | Win N=16 fair bench(同上) | Win | 50K frames 各,串行,同 commit;Win box 只跑这次 |
| T-C3 | 决策:若 Mac+Win 都达 gate → 标 Python mp legacy / 进 P2 paradigm port;否则反思 | — | 写决策 memo 进 i29-go-actor-pool/design.md |

### Out of scope(本 plan 不做)

- F1D4 minimax 算法优化(B-compile-train backlog,P3)
- CUDA caching 释放(Win+cu130 平台限制,Linux 才能修)
- AZ / PPO / CFR / BC paradigm Go-actor port(I29 Phase 2 work,perf 通了再做)
- BC dataset-driven backend(I29 Phase 2)
- Static obs cache warm-up 优化(MEDIUM bottleneck,可后续单 task)

## Acceptance criteria(全 PASS 才算关 session goal)

1. **Phase A 5 task 全 ship**,每 task 走 implementer + spec reviewer + code reviewer 三阶段
2. **Mac N=4 smoke**:Phase A 完后 instrumentation 全部 emit 到 metrics.jsonl,无 regression
3. **Phase B fix 完成**,Mac N=4 fps 提升 ≥ 1.5x(current 16 fps/actor → 24+)
4. **Phase C bench 数据**:Win N=16 fps ≥ 70 + Mac N=4 fps ≥ 45,所有低于理论极限的 stage 有可信解释
5. **决策落盘**:design.md 加 「Phase B 完成 + 实测 fair benchmark」 section

## 工作流约束(subagent-driven-development)

- 每 task 派 implementer subagent + spec reviewer subagent + code quality reviewer subagent
- Phase A 5 task 可串行 dispatch(共享 logging.py + go_collector.py 文件,并行有 git race 风险 per
  [[feedback_parallel_implementer_git_race]])
- Phase B 3 task 必串行(共享 transition_writer.go / pool.go / InfServer)
- 每 task commit 单元 = 一个逻辑变更,commit body 含 why + tradeoffs(per CLAUDE.md)
- 跑 Win 前必须 Mac smoke 全过,否则不跑
- Win 跑 1 次 = Phase C T-C2,数据出后再判 Phase B 是否够,不够则再补 Phase B 任务

## Risk

- **Phase B 改 InfServer batching** 是大改造,可能撞 mp 路径 regression(Python mp 也 import 同 InfServer)。
  必须配 5 paradigm × mp+Go-actor 路径 smoke matrix 覆盖
- **Win bench 数据可能 contradict 理论模型** — short-run noise / Win allocator stable 状态 / opp_mix
  sample 差异。 须跑 ≥ 50K frames + 弃前 5K warm-up
- **Python mp 35-37 fps baseline 是 memory 记忆**,Phase C 必须 re-run 一次 fair baseline,不引用记忆数字
  per [[feedback_performance_must_verify]]

## T-C1 Mac fair bench 发现(2026-05-24)

Mac N=4 实测 3 seeds × 2 backend (pure collector,no train):

| Backend | fps/actor mean ± std | mem_delta mean |
|---------|---------------------|----------------|
| Python mp | 48.1 ± 12 | +41 MB |
| Go-actor (post T-A1+T-B1) | 12.7 ± 2.9 | +634 MB |

**Python mp 3.8x faster than Go-actor on Mac N=4。**

Root cause(高置信):Python mp 走 SHMRing(in-process shm pipe)推 episode-level
transitions;Go-actor 走 TCP socket per-transition push + decode 走 Python listener
thread(GIL contention)。 mac N=4 不存在 mutex 争抢仍 12.7 < 48 = TCP path 整体
overhead 是结构性,T-A1 + T-B1 只解了 mutex 段。

详 `tools/_bench/mac_collector_results.md`。

## 后续路线(user 决策 framework,2026-05-24)

T-C2 Win bench 出后,按数据决主路线。 每路线 **新 branch 检出当前 commit**(user 指示)
独立 ship,失败可弃:

- **路线 A**:Go-actor SHMRing(替换 TCP) — branch `feature/i29-go-actor-shmring`
  - cross-language mmap'd ring buffer。 LOC ~500+。 高 risk 高 ROI
- **路线 B**:Go-actor in-process(替换 socket,走 cgo callback) — branch `feature/i29-go-actor-inproc`
  - 反向 cgo 反 Python。 LOC ~300。 cgo + GIL + Go runtime 交互 risk 高
- **路线 C**:接受 Python mp 胜,归档 I29 — branch `feature/i29-archive`(只 cleanup + memo)
  - 把 Go-actor 当 educational + Python mp 继续优化(InfServer GPU pipeline 等)

判断标准(T-C2 Win 数据):
- 若 Go ≥ Python @ N=16:**路线全 skip**,Go-actor 已超 Python,ship 即可
- 若 Go 接近 Python(>=80%)@ N=16:路线 A(投资最大改造)
- 若 Go 仍 1.5x+ 落后 @ N=16:路线 C(架构上 Go-actor 不适合 GICG)+ Python mp 继续

## T-B-decide outcome(2026-05-24)

基于 (1) Phase A 5 task 全 ship + Mac verify 通过 (commit c8a571d) (2) Win N=16 历史 perf trace 数据
(prior session 2026-05-24 run `000110`) (3) 理论极限模型 (perf_plan §理论性能模型),决策:

### T-B1 — DO IT(必须,Win N=16 主瓶颈直接 fix)

`TransitionWriter` per-actor conn(去单 mutex)。 证据:
- Win N=16 实测 push concurrency 7.42 / mean 1081 ms/call —— mutex_wait 是 dominant
- 理论模型:single mutex cap 6.8 trans/s,N=16 linear scale 上限 77 trans/s
- 当前实测 Win 1.92 trans/s = push 上限 28% 而非 linear 上限 2.5%
- T-B1 移除 mutex 后 N=16 实际上限走向 linear scale(InfServer GPU + driver consume 是更高上限)

注:Mac N=4 不显 mutex contention(只 4 goroutine 偶尔同时 push),所以 Mac perf 提升 不会很大 — 这是
**Win-specific bottleneck**,但 fix 普适架构改善,Mac 也无 regression。

### T-B2 — DEFER 到 T-C2 Win bench 数据后

Inference batching coalescer。 证据 + 推理:
- Win N=16 batching_efficiency 5.5% (batch_avg 1.6 vs target 8-12) — under-batched
- 但 T-B1 移除 push mutex 后,Go-actor 吞吐预计 ~7-10x 提升(1.92 → ~13-19 trans/s),自然产生
  更多并发 inference request → batch_avg 自动上升(driver-controlled batching window 不变,但
  filling rate 7-10x → batch fills 满才 forward 的几率 ↑)
- T-B2 是 ~150 LOC 大改造,改完可能 touch Python mp path regression。 在不必要的情况下不动
- 先做 T-B1 + Win bench(T-C2),若 batch_avg 仍 < 5,再 trigger T-B2

### T-B3 — DEFER 到 T-C bench 数据后

Python listener / driver path instrumentation。 证据:
- Mac N=4 verify 显示 driver 端 assembler.ingest spans 全 emit
- 但 prior Win run 未 instrumented driver 端 → 不知 driver 是不是真瓶颈
- 先做 T-B1 + Mac smoke + Win bench,实测 driver 慢则 trigger T-B3 补 listener recv/decode/enqueue 时长

## 下一步执行序列

1. **T-B1**(必)→ Mac smoke verify no regression + 可能 +5-10% Mac fps
2. **T-C1**(Mac fair bench Python mp vs Go-actor):看 Mac N=4 / N=8 是否达 Go ≥ Python
3. **T-C2**(Win N=16 fair bench):决定 Phase B 是否需要 T-B2/B3 补丁
4. **T-C3**(决策 memo):若 Win gate 达 → Python mp legacy + 进 P2 paradigm port
