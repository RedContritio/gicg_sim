---
change_id: az-mp-pool-unification
capability: training-architecture
delta_type: NONE
target_subtopic: actor-backend
---

# Spec Delta — training-architecture / actor-backend

> # Spec changes: TBD per D1-D5 decisions in design.md
>
> **Current placeholder under D4 推荐 (A)** (无 spec 改动 — AZ reuses AB13
> 第 1 escape hatch `inference_client`, DMC pattern):此 patch file 不引入
> 新 SHALL。 AZ port 是 AB13 的第二个 user (after DMC), DMC entry 早 ship
> 时 AB13 已 cover "DMC pattern, parent-constructed InferenceClient handle
> attached to shared InferenceServer";AZ port 接通后 AB13 文字一字不需改。
>
> 若 user 决 D4 改选 (B) (AB14 codify "AZ selfplay 共享 InferenceServer + N
> InferenceClient pattern"),此 file 改 stub 实质内容 — 留 TBD 直到 D4 拍板。

## [NONE] No spec change required

**Rationale**:
- AB13 (`actor_backend.md` § 3.6) 已 codify `actor_main` 双 escape hatch:
  `inference_client` (DMC pattern) + `provider_kwargs` (PPO pattern, 互斥)。
- AZ port 复用第 1 escape hatch — `build_az_provider(cfg, actor_id, *,
  inference_client)` 签名与 `build_dmc_provider(cfg, actor_id, *,
  inference_client)` 一致;AB13 dispatch matrix (line 65) 已显式 cover
  ("if inference_client is not None: provider = build_provider(cfg,
  actor_id, inference_client=inference_client)")。
- AB1-AB12 不动 (`actor_backend` dispatch / N+2 OS process topology / 0 cgo /
  TCP-only inference wire 等 Go backend-specific 约束 — 与 AZ Python backend
  port 完全无交集)。
- AB3 status 表 (AZ='不 support actor_backend=go') 不动 — Go backend 是
  独立 follow-up backlog,与本 change 正交。

## Live spec update (post-implement,non-spec-changing)

实现完成后 `actor-backend.md` § 4 Code references 加 AZ entries (live spec
update, NOT spec change):

```diff
- `training/paradigms/ppo/_async.py:PPOAsyncCollector.__init__` —
  `provider_kwargs` pattern (AB13 第 2 escape hatch)
+ `training/paradigms/ppo/_async.py:PPOAsyncCollector.__init__` —
  `provider_kwargs` pattern (AB13 第 2 escape hatch)
+ `training/paradigms/az/collector.py:AZAsyncCollector._bootstrap` —
  `inference_client` pattern (AB13 第 1 escape hatch, 与 DMC 同 path) +
  InferenceServer 起 (network_factory_path / inference_handlers_module_path
  注入 AZ network.Agent + _inference_handlers)
+ `training/paradigms/az/mp_factories.py:build_az_provider` — 显式
  `inference_client` kwarg + _AZRemoteProvider 包 client.request
```

此 reference 块更新随 live spec 写入,**不需要进本 change patch**。

## If D4 flips to (B) (future possibility)

若决策 D4 改选 (B),本 patch file 改 stub:

```markdown
## [ADD] § 3.7 actor_main inference_client selfplay-mode reuse

**AB14**: AZ selfplay 模式 SHALL 通过 `inference_client` escape hatch 接
parent-constructed `InferenceClient`,N InferenceClient 共享同一
`InferenceServer` (1 server : N actor)。 InferenceServer SHALL 接
`network_factory_path` + `inference_handlers_module_path` 注入 AZ-specific
network class + game_start / eval_batch handler。 SelfPlay 两 side 共用
同一 network (A5.2),actor side 无需 challenger / champion 区分。
```

但本 DRAFT 推荐 D4 选 (A) — 不引 AB14, 信息冗余。

## Code references (本 change 内 — implement phase 后填实质)

待 T1 / T2 / T4 实现后填:

- `training/paradigms/az/mp_factories.py:_AZRemoteProvider` — 持
  InferenceClient + 提供 `game_start` / `eval_state` / `forward` 给
  AZEpisodePolicy
- `training/paradigms/az/mp_factories.py:build_az_provider` — `inference_client`
  显式 kwarg, 不接 `provider_kwargs`
- `training/paradigms/az/collector.py:AZAsyncCollector._bootstrap` —
  InferenceServer + N InferenceClient 起 + Runtime.start_actors 注 client
- `training/paradigms/az/train_loop/async_loop.py:run_async` —
  ParallelInferencePool → AZAsyncCollector 切换 + ingest_thread 改 collect-drain

## Test references (本 change 内)

- `training/paradigms/az/tests/test_az_async_collector_inference_server_handoff.py`
  (NEW) — 验 AB13 第 1 escape hatch dispatch (in-proc actor_main,mock client)
- `training/paradigms/az/tests/test_az_async_collector_e2e.py` (NEW,
  smoke_full marker) — 2-actor 真 spawn + N=2 InferenceClient + 5 episode
  + clean shutdown
- `training/tests/test_az_smoke_full.py` (现存) — production train_az
  lifecycle zero-regress gate (post-T4 切换后必须 PASS)
