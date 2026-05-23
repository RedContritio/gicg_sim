# Design — Go-native actor pool (c-shared lib)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Python master process (training/core/pipeline.py)            │
│                                                              │
│   MetricsLogger ──┐                                          │
│                   │ attach_external_queue                    │
│   collector ──┐   │                                          │
│               │   │                                          │
│    ┌──────────▼───▼──────────────────────────────────┐       │
│    │ libgicg_actor.dll/.dylib (ctypes-loaded)        │       │
│    │ ──────────────────────────────────────────────  │       │
│    │ Go runtime (single, lazy-init on first call)    │       │
│    │ ┌─────────────────────────────────────────────┐ │       │
│    │ │ gicg_actor (RL,新顶层 package)              │ │       │
│    │ │  ├─ pool.go (N goroutine 调度)              │ │       │
│    │ │  ├─ episode.go (主 loop,跑 engine.Step)     │ │       │
│    │ │  ├─ inference_client.go (socket → InfServer)│ │       │
│    │ │  ├─ shm_ring.go (transition SHM writer)     │ │       │
│    │ │  ├─ adapter.go (paradigm 注册表)            │ │       │
│    │ │  └─ dmc/                                    │ │       │
│    │ │      ├─ obs_encoder.go (DMC numpy 协议 port) │ │       │
│    │ │      └─ greedy_player.go (F1-D2/D4 port)     │ │       │
│    │ │                                              │ │       │
│    │ │ import "<module>/gicg_engine" (单向)         │ │       │
│    │ └─────────────────────────────────────────────┘ │       │
│    │                                                  │       │
│    │ Transition out:                                  │       │
│    │  SHM ring buffer (Go writes, Python reads via    │       │
│    │  ctypes get-ring-head + np.frombuffer view)      │       │
│    └──────────────────────────────────────────────────┘       │
│                                                              │
│  libgicg.dll (现有,不动 — engine only,Python ctypes call)   │
│                                                              │
└─────────────────────────┬────────────────────────────────────┘
                          │ socket (raw bytes + length prefix)
                          ▼
        ┌────────────────────────────────────────┐
        │ Python InfServer subprocess (unchanged) │
        │  — torch + cuda + batched_forward      │
        └────────────────────────────────────────┘
```

## 边界原则

**`gicg_engine = environment only`,RL-zero awareness**:engine package 不含 actor / opp / obs encoder /
inference client 等任何 RL 概念。 这是硬约束,任何修改 design 时不可破。

- `gicg_engine/`(现有,40k LOC Go)+ `gicg_engine/capi/`(现有 `libgicg.dll`): 不加文件、不改一行
- 新 `gicg_actor/`(顶层目录,跟 `gicg_engine/` 并列): 所有 RL Go code
- `gicg_actor` 内部 `import "<module>/gicg_engine"`(单向依赖)
- `libgicg_actor.dll/.dylib` 独立于 `libgicg.dll`(各含 Go runtime ~10 MB,保边界的代价)

## Core decisions(锁定)

### D1 — Engine 复用:native Go import,no cgo

Go actor 在 `gicg_actor/` 包内 `import "<module>/gicg_engine"`,直接调 `engine.Step()` /
`engine.Clone()` 等 — native Go function call,无 cgo overhead(对比 Python ctypes ~1-5 μs / call)。

理由:Python 调 `gicg_engine` 走 c-shared 仅因 Python 不能 import Go;Go-side 无此限制。 "纯 Go 5000+
LOC 重写" 是错误 framing — engine 已经是 Go,actor 直接复用。

### D2 — F1-D2/D4 opp:Go 全 port + **winrate gate** 验收

`greedy_player` + `greedy_dice` + minimax tree → Go 重写,~500-800 LOC。 actor goroutine 内跑 opp
self-play,**不 move 到 InfServer**(跨 paradigm boundary 风险大)。

**验收用 winrate gate 而非数值等价**:

- F1-D2 vs Python F1-D2:跑 n=128 swap matches against random,winrate 落 Python baseline 95% CI 内
- F1-D4 vs Python F1-D2:跑 n=128 swap matches,Go-D4 winrate 应该接近 Python-D4 vs Python-D2 baseline
- 完全绕过浮点 ordering / depth-4 路径依赖,直接行为等价

理由:depth-4 minimax 浮点 score 累积 + tie-breaking 顺序在不同语言不可控,bit-exact 不实际。 行为等价
是真正想要的 — RL signal 看 opp 强度,不看 micro-decision。

### D3 — Paradigm scope:主体 paradigm-agnostic + per-paradigm adapter

Go actor pool 主体(`gicg_actor/{pool,episode,inference_client,shm_ring,adapter}.go`)**本就 paradigm-
agnostic**:

- pool.go:N goroutine 调度,跟 RL 算法无关
- episode.go:engine.Step() 主 loop,跟 paradigm 无关
- inference_client.go:socket → Python InfServer,纯 IO
- shm_ring.go:transition 写 SHM,跟 schema 无关
- adapter.go:paradigm 注册表,提供 `ObsEncoder` + `OppBaseline` interface

Paradigm-specific 只两块,各 paradigm 提供自己实现:

- `ObsEncoder.Encode(engine_state) → []byte`(numpy ndarray raw bytes)— DMC 一种 schema,AZ / PPO /
  CFR 各自不同 schema
- `OppBaseline.SelectAction(state, role) → ActionRef` — DMC F1-D\*,AZ PUCT,PPO/CFR 各自

**Phase 1 ship `gicg_actor/dmc/`**(DMC adapter — obs encoder + F1-D\*);**Phase 2 per-paradigm port**
(`gicg_actor/{az,ppo,cfr,bc}/` 各一)。 Python 侧 `training/core/actor/backend.py` 加抽象 protocol
`ActorBackend`(`PythonActorBackend` + `GoActorBackend`),collector 通过 cfg flag 选 backend。

### D4 — Build:libgicg_actor 独立,不合并到 libgicg

`gicg_actor/capi/` 新建 `package main` + `//export` C API + `cgo_export.go`,build:

```bash
go build -buildmode=c-shared -o gicg_env/libgicg_actor.dylib ./gicg_actor/capi
# Win:
go build -buildmode=c-shared -o gicg_env/libgicg_actor.dll ./gicg_actor/capi
```

Python master `ctypes.CDLL('libgicg_actor.dll')` load。 lifecycle 绑 Python master(Python exit →
atexit hook → ctypes call `StopActorPool()` → Go runtime cleanup)。

**为什么不合并到 `libgicg`**(我之前推荐过合并,user pushback 修正)— 因为 `gicg_engine` 是
environment only,合并到 `libgicg` 会让 engine lib 含 RL code,破坏边界。 两个 lib 各自含一份 Go
runtime ~10 MB 是保边界的代价,可接受。

### D5 — IPC 协议:raw bytes + length prefix(research verified)

Go actor ↔ Python InfServer 走 localhost TCP socket,wire format:

```
[2B ver][16B static_hash][4B client_id][4B req_id][2B n_dyn][2B n_refs][2B n_pay] | dyn_obs.bytes | refs.bytes | pay.bytes
```

Go 端:`binary.LittleEndian.PutUint16` 写 header + 3 个 `unsafe.Slice((*byte)(unsafe.Pointer(&arr[0])), n*4)`
写 numpy contiguous bytes。 Python 端:`recv_into` 进预分配 4KB bytearray + 3 个 `np.frombuffer(buf, dtype=np.float32)`
**zero-copy view**(不 copy)。

**Research 验证**(IPC research agent 2026-05-21):

| 方案 | 实测 RTT | 障碍 |
|---|---|---|
| **raw bytes(选定)** | <1μs | 无 |
| Cap'n Proto | 2-5μs | Cap'n Python Win 3.13 wheel 刚 ship 2026-01,wheel 风险;Python builder API arcane |
| Apache Arrow IPC | 10-50μs schema overhead per stream | 是 batch-oriented,4 KB single-request 粒度用错 |
| protobuf | 5-15μs | numpy float array 走 `bytes` 字段是 copy(zero-copy 被吃)|
| FlatBuffers | 3-8μs 读,Python 写 unusably slow(known issue #4668) | 写不达 5μs 预算 |
| msgpack-numpy | 5-20μs | msgpack-numpy 库 12+ 月未维护 |

5μs 预算下唯一 viable 是 raw bytes。 schema **本身就是** Go side header struct + Python side
`struct.unpack` 对照 — 无 schema 抽象层。 跨语言客户端要 ≥ 3 种时再考虑 Cap'n Proto。

### D6 — Phase 1 直接 production scale

user pushback:不接受 random opp + zero-logits mock。 P1 即 production scale e2e,包含 F1-D2/D4 +
真 InfServer + 真 obs encoder + N=16 production cfg Win 实测 fps gate。

Phase 数从 7 压缩到 4(详 `tasks.md`):

| Phase | scope | LOC | Verify gate |
|---|---|---|---|
| 0 scaffold | hello-world ctypes + Go SIGTERM handler + 跨平台 build + libgicg 不受影响 smoke | ~250 | 100 次连续 Mac+Win 不 hang;libgicg 现有 Python tests 全 PASS |
| 1 production e2e | `gicg_actor/{pool,episode,inference_client,shm_ring,adapter}.go` + `gicg_actor/dmc/{obs_encoder,greedy_player}.go` + Python `GoActorBackend` ctypes wrapper + DMC collector 接 | ~2200 | obs encoder bit-exact 10k random + F1-D\* winrate gate + N=16 Win 实测 fps ≥ 70(2x baseline 35) |
| 2 paradigm adapter port | `gicg_actor/{az,ppo,cfr,bc}/` 各 obs encoder + opp baseline(per-paradigm 单独 sub-PR) | ~300 + per-paradigm | 5 paradigm smoke + smoke_full 全 PASS |
| 3 production train | stage3_b_v_legacy.toml 整局 1M frames N=64 + Mac gauntlet 验证收敛 | — | wp vs F1-D2 落 baseline 95% CI |

### D7 — Transition push:localhost socket(raw bytes + length prefix)

**修正(2026-05-21,P1.1 implementation 阶段发现)**:原 design 默认 "reuse SHMRing 协议"
不可行 — `training/core/actor/ipc/ring.py` 用 `mp.Lock` + `mp.Value` 是 Python multiprocessing
specific(POSIX semaphore / Win Mutex 的 Python wrapper,internal layout 不 documented),Go 端
无法可靠 mirror sync primitive。 用 raw mmap + atomic ops + custom spinlock 重设计跨语言 SHM 协议
是 ~500 LOC + 跨平台测试,scope 大风险中。

改默认:**localhost socket(同 D5 IPC 协议同向)**。 Go writer → Python reader 走第二条 socket
(独立于 D5 InfServer socket),raw bytes + length prefix wire format。 RTT ~3μs sub-ms,production
N=16 实测 transition aggregate ~20/s,socket 完全够。

defer 真 SHM 优化到 Phase 3 perf 数据驱动:若 P1.5 Win 实测 transition push 真成瓶颈再重设计协议;
不然 socket 是更 KISS 选择(同 IPC 一份 wire format codebase,无第二种 sync primitive)。

Python 端 collector 适配:`training/core/actor/go_backend.py` 加 transition socket listener +
reader thread → push 进 paradigm collector 的 transition queue(现 DMC collector 用 SHMRing reader,
Go backend 换成 socket reader,collector interface 不变)。

### D8 — Phase 1.5-R 闸门收尾:管线穷举审计 + 3 个耦合修复簇

**修正(2026-05-23,T-R3 Win N=16 stress 后)**:T-R3 真网络压测暴露 Go-actor → driver
管线远比 D6/D7 假设的不完整。 做了全管线穷举审计(本 session 我审 + 独立 reviewer 复核 +
关键 claim 亲验代码)。 RSS 10.5GB 与 driver 0.4 eps/s 两个故障现象的根因已确定:

**审计纠正的错误前提**:D5 默认 "Go actor inference 走 batched InfServer" —— **错**。
`_socket_decoder.py:build_dmc_socket_forward_callback` 每 request 同步单条 forward,从不入
`request_q`;`inference_server_socket_listener.py` docstring 自承 "P1.3c 优化合 batching"
—— **P1.3c 从未 ship**。 加上 `inference_client.go` 单 conn + `Request` 全程持 mutex(协议
无 request_id 乱序应答能力),Go 端 N actor 任意时刻仅 1 个 in-flight inference。 → `0.4
eps/s` 主因是 inference 结构性 single-flight,非 GIL / GPU 争用,**代码可读出无需 measurement**。

修复按 3 个耦合簇组织(**簇内必须一起改** —— 改一个会破坏另一个的假设):

**簇 1 — backpressure + 队列有界化**(RSS 10.5GB 直接机制)
- 现状:`_ready`/`_buffers` 无界 + 全链路无回压(Go `Push` fire-and-forget,Python listener
  一直排空 socket → TCP buffer 永不满 → Go 不限速)+ `collect()` cap 后**静默丢 episode**
  (`go_collector.py:191`)。
- 设计:listener thread 减负 —— 只 recv + 解 envelope + `put` 进**有界 queue**;重组装
  (`_capture_obs_np`)移到 driver 线程的 `collect()` 内(同时解 #14 listener 饿死 driver)。
  有界 queue 满 → socket 回压 → Go `Push` 阻塞。 `collect()` 改为 leftover 留到下次 drain。
- **约束(#12)**:Go `TransitionWriter.Push` 有 `SetWriteDeadline(io_timeout=30s)`,回压阻塞
  超 30s → write 错 → actor goroutine 当 fatal 永久死亡。 回压设计必须:回压阻塞窗口 < 30s,
  或 Go `Push` 改为重试不致死 actor。

**簇 2 — inference 真 batching**(0.4 eps/s 主因,fps 闸门关键路径)
- 设计:InfServer socket listener 把请求 enqueue 到 `request_q` 走批处理 + per-conn response
  路由(完成 docstring 里 deferred 的 P1.3c)。 Go 端去单 conn mutex —— per-actor
  `InferenceClient` conn,或 socket 协议加 `req_id` 支持乱序应答。 两者必须一起改:只改一边
  仍是逐条。

**簇 3 — episode 终结契约**(`_buffers` 泄漏 + winner 正确性)
- 现状:`paradigm.go:252` `MaxEpisodeSteps` 截断时循环正常退出,**最后一条 transition
  `Done=false`** → assembler 永不 assemble → `_EpisodeBuf` 永久泄漏(GICG ~340 步截断是常态,
  见 memory `Episode Step Bound`)。 winner 仅凭 `buf.payloads[-1].reward` 推断(`_go_assembler
  .py:148`),截断 episode 误判 draw。
- 设计:截断时给最后一条 transition 置 `Done=true`(或补发 terminal transition);winner 从
  engine `Winner`/`Phase` 取,不靠 last reward。

**独立修复**(不阻塞主链,可并行):静默路径改 fail-loud(reshape size mismatch /
`pickActionEpsilonGreedy` logits-nLegal 不一致 / listener bind 失败静默 set ready_event);
actor goroutine 死亡可见性(`pool.go` 不补充不报告 → 吞吐看似"慢"实为 actor 在减少);
wire header struct version/size 运行时交叉校验;`np.frombuffer` 零拷贝视图钉住 1.2MB
static blob(首条 transition)。

闸门:T-1.23 仍要 fps≥70 且 mem≤2GB 同时成立 —— 簇 1 保 mem,簇 2 保 fps,缺一不可。

**T-RR.9 实测后 闸门修正(2026-05-23,user 「实测 ≈ 理论值」工作流)**:T-1.23
原数值闸门(fps 70 / mem 2GB)在 Win+cu130 平台约束下不达。 user 替换为 工作流:
**理论值 — 实测 = 浪费,系统消除浪费**。 mem 大头由 D9 解(见下);fps 25 是
合理上界(N=16 + opp_mix `f1d4=0.20` D4 minimax 占 1/5),非可压点 — 收益取决
于后续 actor-side opp 优化 / Linux 验证(cu13 expandable_segments 支持)/
historical 真 ring(D10 follow-up,task #3)。

### D9 — Mem 真 root cause:wire + buffer 全程不 pad refs/pay(2026-05-23)

**修正 D8 簇 1 假设**:簇 1 backpressure 解了 `_ready` 无界堆 → wire queue 满载
有界,但 mem 真大头不在 wire queue 大小,而在 **每条 transition payload 含 96%
padding 0**。

**第一性原理推算**(`tools/_dev/mem_probe.py` + mac long probe 实测验证):
production cfg `max_actions=2048`,Go `EncodeDmcTransitionPayload`(`gicg_actor/
dmc/paradigm.go:359`)把 refs/pay 整 padded 推 → 每 transition ~110 KB(action_
refs 2048×3 i64 = 49 KB + action_payments 2048×8 f32 = 65 KB,其他 ~1 KB)。
buffer-cap = 200_000 trans × 110 KB = **24 GB master mem 上限**。 实测 Win N=16
mem slope 4.2 MB/s 严丝合缝 = 25 fps × 110 KB + Go runtime grow 1.2 MB/s。

**修法(3 commit 链,branch `feature/tools-runs-fixes`)**:
- `a8123f8`:queue 4096 → 256 + `np.frombuffer` 加 `.copy()` 解 view-pin。 wire
  文件 tracemalloc 675 → 49 MB plateau。 mac active mem 接近理论。
- `1594a33`:Go runtime.MemStats expose 经 capi → mem_probe 集成,split Go heap
  vs Python heap vs native。 audit 确认 Go side ≠ leak(HeapAlloc 130 MB 稳)。
- `1687f5d` **root cause**:wire v2→v3 BREAKING,refs/pay 不再 padded;`collate_
  batch` 移 `action_refs/payments/legal_mask` 到 variable section,batch sample
  time pad 到 `cfg.max_actions`(network forward 不变,只是 buffer storage
  nlegal-sized)。 DMC + PPO + AZ scaffold 对称改 5 layer(Go encode + wire +
  assembler + `_capture_obs_np` + collate)。 235 LOC / 15 files。

**Win N=16 verify run `artifacts/202605230659_000109_dmc_stage3_b_v_legacy_go`**:
- baseline t=180s master_rss 2670 MB(vs T-RR.9 同期 3742 MB,**-1072 MB**)
- slope 1.5 MB/s(vs T-RR.9 4.2 MB/s,**~3x 降**)
- 预测 plateau ~14 GB(buffer 200K × 12 KB + baseline + 1.5×8000s 至满),vs
  pre-fix 24+ GB 不可达 → 长跑 11 hour 可完成
- mac `_decoder.py` 22→1 MB/sample(20x),Go HeapAlloc 280→130 MB

**承接 user 「不重复造轮子」原则**:`tracemalloc_total_mb` 加进 `_sample_mem()`
(commit `895d446`),production run 自动 emit metric record;`mem_probe.py`
缩窄到只 Python heap top-N per-file 归责 + delta(metric 不含的 unique 部分),
不再重复 psutil RSS 采样。

**ckpt 兼容**:`DMCBuffer.state_dict` 只存 capacity 不存 transitions,wire v2→
v3 BREAKING change 不破 ckpt resume。

**Follow-up(task #3)**:Go-actor `oppHistorical` 走 current net proxy(cost-
faithful self-play 等价),真 historical-net ring 待 D10(下次 production run
评估 ROI 后决)。

## ADR-agent 自定 trade-off(决定后内联)

### 数值等价 tolerance

- **obs encoder**:bit-exact(`np.array_equal`)— numpy 协议明确,Go port 用相同 typed segment offsets
  + 相同 float32 ops,可保 bit-exact。 测试 10k random observation,Python vs Go byte-equal
- **F1-D2/D4 opp**:winrate gate(详 D2),不做 bit-exact 也不做 ε-tolerance

### Go package layout

```
gicg_actor/                          # 新 — 跟 gicg_engine/ 顶层并列
├── go.mod (顶层 module,继承 gicg_engine 同 module 路径) 或 单独 sub-module
├── pool.go                          # N goroutine 调度
├── episode.go                       # episode 主 loop
├── adapter.go                       # paradigm 注册表(ObsEncoder/OppBaseline interface)
├── inference_client.go              # socket → Python InfServer (raw bytes)
├── shm_ring.go                      # transition SHM writer
├── *_test.go                        # Go unit tests
├── capi/                            # c-shared export 入口
│   ├── main.go                      # //export C API
│   └── cgo_export.go                # type 转换 + 错误处理
└── dmc/                             # P1 — DMC paradigm adapter
    ├── obs_encoder.go               # numpy 协议 Go port
    ├── greedy_player.go             # F1-D2/D4 Go port
    └── *_test.go

# P2 后扩展:gicg_actor/{az,ppo,cfr,bc}/  各 paradigm 各自
```

### Risk + mitigation

| risk | mitigation |
|---|---|
| cgo + Python signal handler 互相影响(memory: `feedback_go_cgo_signal_handler`)| Go init 必装 `signal.Notify(c, syscall.SIGTERM); <-c; os.Exit(0)` no-op handler。 P0 hello-world 守 100 次连续不 hang |
| Go runtime 在 c-shared 模式生命周期(no main goroutine,init order)| P0 hello-world 验证 Python load → ctypes call → goroutine 起 → ctypes call stop → join。 atexit hook 兜 cleanup |
| obs encoder Go port 数值漂移 | bit-exact test 10k random observation,CI gate |
| F1-D4 浮点 ordering 不可控 | winrate gate 验收(行为等价 > 数值等价) |
| `libgicg` + `libgicg_actor` 双 lib Python 同时 load 时 ctypes symbol clash | 各 lib `//export` 函数名 prefix(`gicg_*` vs `gicg_actor_*`),编译 + load 测验证 |
| Win c-shared mode mmap SHM 跨平台细节 | reuse 现有 Python `shm_ring.py` 跨平台模式,Go side mirror;P0 加 SHM round-trip smoke |
| paradigm-agnostic boundary 重切 az/ppo/cfr/bc 适配工作 | Phase 2 单独 sub-PR per paradigm,本 ADR 仅 DMC adapter |

## References

- backlog I29 原始描述: `docs/3_plans/backlog.md` line 80
- 2026-05-21 perf 验证 session 数据: `docs/3_plans/backlog.md` I26 (2026-05-21 reverse) + 本 session
  metrics.jsonl
- IPC protocol research(本 ADR design 阶段 dispatch): raw bytes 选定理由 (D5 表格)
- memory `feedback_go_cgo_signal_handler` — c-shared Go SIGTERM handler 必装
- memory `reference_genius_invokation_clone` — Guyutongxue/genius-invokation TS 实现可对照 F1-D\* algo
- `training/core/actor/inference_server.py` — Python InfServer(Go actor 走 socket 接)
- `training/core/actor/shm_ring.py` — 现 Python SHMRing 协议(Go writer 端 mirror)
- `gicg_engine/capi/` — engine c-shared 现 layout(`gicg_actor/capi/` 模仿同模式)
