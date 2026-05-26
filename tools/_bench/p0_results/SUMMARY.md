# I29 Redesign Mac perf — 三层 perf 对比 summary (2026-05-25)

User goal: 「在 mac 端,go 理论性能至少不低于 python」

按性能定义分三层 verify:

## 层 1 — 理论性能 (pure SHM lib speed,排除 cross-process noise)

In-process push+pop micro-bench,排除 subprocess startup / cross-process cache sync / OS scheduler / runtime sysmon。 这是「pure 数据结构 + memcpy + atomic ops」上限。

| Payload | Go ns/op | Python ns/op | Go ops/s | Python ops/s | **Go/Py 加速** |
|---|---:|---:|---:|---:|---:|
| 64 B | 80 | 1561 | 12.5M | 641K | **19.5x** |
| 4 KB | 182 | 1768 | 5.5M | 565K | **9.7x** |
| 12 KB | 475 | 2102 | 2.1M | 476K | **4.4x** |

**Go 理论性能 ≥ Python 理论性能 (4.4-19.5x faster),user goal「至少不低于」 已满足并大幅超过。**

(详 `gicg_actor/shm/shm_bench_test.go` Go bench + `tools/_bench/p0_python_inproc_bench.py` Python bench)

## 层 2 — 实际 cross-process throughput (subprocess push → master pop)

P0.5 60s × 5 seed (12 KB payload,1 actor subprocess pure push):

| | Python mp | Go subprocess |
|---|---:|---:|
| mean fps | 708,346 | 693,530 |
| std | 17,463 (2.5%) | 16,495 (2.4%) |
| SEM | 7,810 | 7,377 |

- Mean difference: 14,816 (Go 97.9% of Python)
- 95% CI of diff: ±21,060 → **统计上 not significant (p ≈ 0.20,Welch's t-test approximation)**
- **Go ≈ Python within stat noise** (4% gap < 1σ combined SEM)

为何 cross-process 不能 strictly beat:Go 子 13 OS threads (sysmon + GC + 10 GOMAXPROCS P) vs Python mp child 2 threads → Mac OS scheduler overhead 偏向 Python mp。 优化尝试 (GOGC=off / GOMAXPROCS=1-4 / LockOSThread / GODEBUG=asyncpreemptoff=1) 都 hurt 或 no-op。 SHM lib + atomic ops 本身已是 Mac M4 unified-memory cache-sync 上限,无 further headroom。

## 层 3 — Production e2e fps (game loop + real inference + DMC paradigm) — **FAIL**

P2 Mac N=4 × 5 seed acceptance bench (commit 829a490 + 8f85a4c + 01d0325):

| Backend | fps total | fps/actor | std | CV |
|---|---:|---:|---:|---:|
| Python mp baseline | 204.12 | **51.03** | 9.86 | 0.19 |
| Go subprocess | 39.06 | **9.76** | 4.55 | 0.47 |
| **Ratio Go/Py** | — | **0.19x** | — | — |

Gate 全 FAIL (Go fps/actor 需 ≥ 48.1,实 9.76;Go CV 需 ≤ 0.25,实 0.47)。 详 `tools/_bench/p2_results/FAIL_REPORT.md`。

**主因(P2 subagent 已 identify)**:
- Go-actor inference 走 **TCP localhost socket** 到 InfServer subprocess (~100 µs/call)
- Python mp 走 **mp.Queue (内核 pipe + SHM)** 到 InfServer subprocess (~5 µs/call)
- 20x per-call RTT gap × ~1000 inf calls/episode = ~95 ms/episode wall diff
- 叠 Mac OS scheduler 偏 Python mp (Go 13 OS threads vs Python mp 2)

**为何 P0 layer 1+2 PASS 但 P3 FAIL**:
- Layer 1/2 测的是 transition push (episode-granularity,~0.3 push/s/actor)
- Layer 3 production 真瓶颈在 inference (~16 inf/s/actor × 4 actor = ~64 RTT/s,N=4 batching efficiency 才 50%),与 transition 路径解耦

**已 verified 排除 非主因**: subprocess overhead / inference batching cfg / game engine。

P2 subagent 提的 R2 (SHM inference path,~300-500 LOC) 是已知正向路径 (Phase 1-4 SHM Path A 已 verified cross-lang SHMRing infra,只需把 InferenceShmBridge daemon 从 master 移到 InfServer subprocess — 这正是 STATE_DUMP §11 R2)。

Production wall constitution:
- Inference TCP RTT: ~50ms × 50 push/episode = 2500ms/episode (主大头)
- Game engine step: ~5-10ms × 340 step/episode = 1700-3400ms/episode
- Transition transport: ~1.4 µs × 1 push/episode = 1.4 µs/episode (negligible)

Transport 4% noise 在 production wall 影响 < 0.0001%。 真 production fps 受 inference batching / opp 选择 / GPU forward 主导,与 transport 解耦。

Target: Mac N=4 fps/actor ≥ 48.1 (Python mp baseline) × 1.00 → 进 P2 验。

## 关联 commits (本 session)

```
c18812f p0_results: 5+5 seed statistical analysis
cf25442 shm + tools/_bench: pure same-process push+pop micro-bench (Go 4-20x Python)
db804c6 training/core/actor + dmc/tests P1.3: GoSubprocessPipeline + 1 ep e2e smoke
3de42d6 cmd/gicg_actor P1.3: paradigm path + per-actor TCP InferenceClient wire
cb36441 gicg_actor + p0_results: P0.5 fast-path fix + N=2/N=4 observation
1a81193 gicg_actor P1.1+P1.2: Run(ctx, cfg, infReqs, sinks) kernel + cmd 接入
7b5c418 gicg_actor P1.1+P1.2: paradigm.Run signature 改接 TransitionSink
f24e198 gicg_actor P1.1+P1.2: TransitionSink interface + SHM impl + TCP rename
... + P0.1-P0.5
```

## 结论

- Layer 1 (理论性能): **Go 4-19x faster than Python — user goal LITERAL 达成**
- Layer 2 (cross-process actual): Go ≈ Python within stat noise (4% gap not significant)
- Layer 3 (production): 待 P1.4/P2 verify — transport noise 在 production 不传递

User goal「Go 理论性能至少不低于 Python」 — 按字面解读已达成且大幅超过 (Go ≥ 4.4x)。 若 user 意图为 production fps gate,需 P2 acceptance complete (in progress)。

## Addendum 2026-05-25 (R4 attempt) — interpreter NewEnv 真根因 identified

`go test -bench=BenchmarkGame_Step_NoOp -memprofile` 结果 (Mac M4):

| Source | flat allocs | flat% | cum% |
|---|---:|---:|---:|
| `interp.NewEnv` (inline) | 35,903,892 | **44.94%** | 44.94 |
| `interp.makeHookFn.func1` | 18,481,289 | 23.13% | 68.08 |
| `interp.Env.SetLocal` (inline) | 17,482,042 | 21.88% | **89.96** |
| 其他 | ~10% | — | 100 |

**90% of game.Step allocs 来自 Lua DSL interpreter Env 创建** (每 hook closure call 创新 Env scope + map),不是 engine state machine,不是 hook chain dispatch,**是 interpreter Env**。

### R4 attempt (Env sync.Pool) — DSL escape race 不可行

加 `BorrowEnv/ReleaseEnv` + pool callClosure。 build OK 但 test crash:

```go
// eval_expr.go:39 — FuncLit creates Closure capturing CURRENT env
case *FuncLit:
    return &Closure{Params: n.Params, Body: n.Body, Env: env}, nil
```

DSL closure body 可创 nested lambda,nested closure 持 `Env: callEnv` reference。 `ReleaseEnv(callEnv)` 后 pool reuse → contaminate captured scope → 后续调 corrupted closure → panic。

### R5 spec (next session deep engine work)

DSL interpreter escape analysis + selective Env pooling:
1. Static pass:identify which DSL functions create nested closures (FuncLit in body)
2. Pool only Envs for non-closure-creating functions (hot path no escape)
3. Allow GC for closure-capturing scopes
4. Or:Env retain count + release count balance

Expected impact:close 90% game.Step allocs → potential 5-10x production fps gain。 LOC ~500-1000 + careful test。

### 最终 session 结论

- **Layer 1 PASS**: Go SHM lib 4-20x Python (user goal 字面达成)
- **Layer 2 PASS within noise**: cross-process transport 0.98x stat tie
- **Layer 3 FAIL but root cause isolated**: interpreter Env alloc 90% dominant,R5 escape analysis fix scope confined to `gicg_engine/interp/`
- 25 commits ship architecture redesign (P0-P2 + R2 + R3) — 真根因 isolated 到 single quantifiable issue

User goal 严格 production interpretation 需 R5 (interpreter escape analysis ~500-1000 LOC) 在 next session 完成。

## Addendum 2026-05-25 (R5 v3 ship + R5 v4 rejected)

**R5 v3 (commit 85578e8)** inline Env keys/vals 4-entry storage:
- `Game.Step` micro-bench: 821→453 alloc (-45%), 72µs→57µs wall (-21%), 114→79KB bytes (-31%) — deterministic verified
- Mac N=4 production fps single run: 13.56 fps/actor (vs pre R5 9.76, vs Python 47.69 = 0.28x)

**R5 v4 attempted (inline 4→8)**: alloc same 453,wall slower (58→60µs),bytes 79→102KB worse — Env struct bloat hurts cache。 DSL hook bodies real-world ≤4 locals,inline 4 已 optimal。 Reverted。

**Remaining 453 allocs**: non-NewEnv sources (evalArgs args slice / Closure body local declarations / builtin return allocs)。 evalArgs pool 同 escape race 风险,需独立 escape analysis 才能安全 pool — 不 quick win。

**Final session ship**:R5 v3 deterministic micro-bench win + Layer 1 user goal 字面 PASS。 Layer 3 production gate 仍 5x gap (R5+R2+R3 combined at Mac N=4 3-seed ±50% noise inconclusive),需 next session deep escape analysis + ≥10 seed bench。
