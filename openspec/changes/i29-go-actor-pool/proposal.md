# I29 Go-native actor pool — c-shared lib extension

**Status:** Proposed (2026-05-21)
**Supersedes:** —
**Superseded by:** —
**Affected specs:** `training-architecture` (actor protocol 通用化);**新顶层 `gicg_actor/` package**(RL-specific Go code,跟 `gicg_engine/` 并列;engine 零侵入)

## Why

2026-05-21 perf 验证 session 在 production cfg (`stage3_b_v_legacy.toml` — d=128 + v_legacy 全 26 张
pool + N=16 actor) 实测 Win 5070 Ti box,InfServer `process_ms_avg = 51.3 ms/batch`,phase 拆分:

| Phase | ms | share |
|---|---|---|
| decode | 35.7 | **69.6%** |
| forward | 14.0 | 27.3% |
| dispatch | 1.6 | 3.0% |

batched decoder 一次失败实验(commit `ba69b15` revert as `b953a7c`)定位**真正瓶颈是 14× pickle.loads
串行**,不是 H2D 也不是 GPU forward。 各 actor 是独立 Python 进程,IPC 走 `mp.Queue` 必跑 pickle —
batched decoder 无法 batch unpickle(各 actor 各自 pickle bytes)。

同时 N=16 actor 占 11.4 GB RSS(单 actor 712 MB),N=24+ 因 mem + Win scheduler oversub 不可行
(backlog I26 ship 时 N=24 因 17 fps 标"勿用",2026-05-21 复跑虽 oversub 退化未复现,但 mem 增 50%
仍是硬上限)。

Python actor 架构本质上 cap 了 fps 上限,**无 pickle 替代方案能突破**(msgpack/raw bytes 单点 ~3-5x
加速 unpickle,但 mem cap + DSL 16× 重复 load + GIL 仍在)。 唯一路径:让 actor 不在独立 Python 进程
内。

## What

**Go-native actor pool — N goroutine 跑在 Python master 进程内**,via 新 `libgicg_actor.dll/.dylib`
(独立于现 `libgicg`)。 不重写 game engine(`gicg_engine` 本就是 40k LOC Go),不动 `gicg_engine`(RL
零侵入),不重写 InfServer(仍独立 Python 进程,actor goroutine socket 接)。

6 个核心设计决策(user 已锁定,详 `design.md`):

1. **Engine 复用**:Go actor 在 `gicg_actor/` 内 `import "<module>/gicg_engine"` 直接 native call ~ns,
   no cgo。 engine package 不知道 actor 存在(单向依赖)。
2. **F1-D2/D4 opp**:Go 重写 `greedy_player` + minimax(actor goroutine 内跑),验收用 **winrate
   gate**(Go-D4 vs Python-D2 跑 n=128 swap 对照 Python-D4 vs Python-D2 baseline 95% CI),不做
   浮点 bit-exact 等价。
3. **Paradigm scope**:**Go actor 主体本就 paradigm-agnostic**(goroutine 调度 / engine.step / SHM
   ring / IPC client)。 paradigm-specific 只两块:obs encoder + opp baseline 各 paradigm 自己 Go
   port。 Phase 1 ship DMC adapter,Phase 2 per-paradigm adapter port(az/ppo/cfr/bc 各一)。
4. **Build 模型**:`gicg_actor/capi/` build `libgicg_actor.dll/.dylib`,**独立于 `libgicg`**
   (`gicg = environment only` 边界禁止合并)。 各自含 Go runtime ~10MB 是保边界的代价。 Python master
   ctypes load,Go goroutine 跑在 Python master 进程内。
5. **Phase 1 直接 production scale**:不接受 random opp + zero-logits mock。 P1 即真 F1-D2/D4 +
   真 InfServer 接 + 真 obs encoder + N=16 production cfg Win 实测 fps gate。
6. **IPC 协议**:**raw bytes + length prefix**(localhost socket,struct.pack header + numpy raw
   bytes,Python `np.frombuffer` view zero-copy)。 research 验证(详 design.md)— 唯一 <1μs RTT
   方案 + stdlib only + Win+Py3.13 零风险。 不用 protobuf / Cap'n / Arrow / msgpack。

预期收益:

| metric | 当前 (Python actor) | I29 (Go actor) |
|---|---|---|
| actor RSS | 11.4 GB (N=16) | < 1 GB (goroutine 几 KB / actor) |
| fps (production d=128 N=16) | 35 | 估 70+(瓶颈转 InfServer 上限) |
| Max viable N | 16-24 (CPU+mem 双 cap) | 64-128(仅看 InfServer 处理速率) |
| DSL load 次数 | N+1(每 actor 一次)| 1(Go binary level)|
| pickle.loads / batch | 14 (35 ms) | 0(in-process channel)|

不在 scope(留 backlog):

- InfServer 多 stream / GPU forward 优化(另一条线)
- 算法层 cache logits per turn(影响 RL signal,另开题)
- InfServer Win cu130 mem 漏(平台限制)
- msgpack / raw bytes pickle 替代(Python actor patch,本 ADR 直接绕过 Python actor)

## Affected specs

- `openspec/specs/training-architecture/`:`actor-backend.md`(新)抽象 `ActorBackend` Protocol —
  `PythonActorBackend`(现 `actor_process.actor_main` + `mp.Queue`)+ `GoActorBackend`(libgicg_actor
  ctypes wrapper)。 collector 在 `attach_metrics_logger` 同模式加 `attach_actor_backend(backend)`
- **新顶层 `gicg_actor/` Go package**(跟 `gicg_engine/` 并列):
  - `gicg_actor/*.go`:goroutine pool + episode loop + IPC client + SHM writer + paradigm adapter
    registry(主体 paradigm-agnostic)
  - `gicg_actor/dmc/`(per-paradigm):DMC obs encoder + F1-D\* Go port
  - `gicg_actor/capi/`:c-shared export 入口 → build `libgicg_actor.dll/.dylib`
  - `go.mod` 顶层 internal `import "<module>/gicg_engine"` 单向依赖

- `gicg_engine/` **零侵入** — 不加文件、不改一行。 若 P2 paradigm port 发现 engine 缺某 API,先单独
  commit 在 engine 侧加 stateless API,actor 再用(commit message 不提 RL,保持 engine 不知道 RL)。
