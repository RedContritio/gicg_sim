---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: az-mp-pool-unification
---

# Proposal — AZ mp actor pool 统一到 core/actor.actor_main + InferenceServer 收口

## 1. Why

I31 backlog #88 (AZ/CFR/PPO mp actor pool 统一到 core/actor.actor_main) audit
显示 AZ paradigm 是 5 个 paradigm 里**唯一同时维护两套 mp pool 实现**的
adapter,且 production 路径 (legacy ParallelInferencePool) 与 unified
pipeline driver 路径 (AZAsyncCollector 用 Runtime / actor_main / SHMRing 已
stub) 并存,N=2 hidden duplication 长期不收敛。 三重痛点:

1. **AZ 有两条 mp 路径并存**:
   - **production 路径**:`train_az()` → `run_async()` (`train_loop/async_loop.py`)
     → `ParallelInferencePool` (`inference_pool.py` 236 LOC) + `InferenceServer`
     起 N worker + dispatch / heartbeat / PoolDeadlock 检测 / cmd_queue / result_queue。
     这是真正跑 production selfplay 的代码,但**完全 bypass core/actor
     基础设施** (Runtime / actor_main / SHMRing / WeightsSHM 一个都没用)。
   - **unified pipeline 路径**:`AZParadigm.make_collector` (`paradigm.py:118`) 在
     `mode='async'` 时返 `AZAsyncCollector` (`collector.py:193`,~108 LOC),
     此 class 走 `Runtime + start_actors + actor_main` 但**没有 InferenceServer
     接入**,且 docstring 直说 "stub-shape only — End-to-end production still
     requires AZ migration off play_self_game onto typed EpisodePolicy"。
   - 结果:两个 collector class 并行存在,production train_az 走第一条,
     unified driver 走第二条;两条都 incomplete (production 不接 actor_main,
     unified 不接 InferenceServer)。

2. **基础设施重复发明**:
   - `ParallelInferencePool` 自己实现 sigterm handler / atexit cleanup / spawn ctx /
     worker proc list / heartbeat thread,而 `Runtime.start_actors` + `ActorProcess`
     已 ship 等价机制 (`actor_process.py:241+` 已含 SIGTERM → SIGKILL 升级 +
     stop_event)。
   - `inference_worker.worker_loop` 自己持 `InferenceClient` + 跑 `play_self_game`,
     而 `actor_main` 已经 spawn-safe + 跑 episode loop + 已经接 inference_client
     (DMC 5 件套 pattern)。
   - heartbeat / PoolDeadlock 是 AZ-specific 检测机制 (MCTS rollout 长 tail
     抗 hang),DMC/PPO 没等价 — 可以是 core/actor 共享机制 (AB14) 或继续保
     AZ-local (mp_factories.py wrap)。

3. **InferenceServer 已 paradigm-agnostic**:
   - `InferenceServer` (`training/core/inference/server.py:38`) 已经在 W2-1/W2-2
     中接 `network_factory_path='training.paradigms.az.network.Agent'` +
     `inference_handlers_module_path='training.paradigms.az._inference_handlers'`
     完全显式注入 — server 端不动,完全可以 reuse 当前 AZ-shaped handler。
   - DMC `_spawn_inference_pool` 已示范 InferenceServer 在 unified pipeline 里
     起的 pattern (DMC 用 socket TCP,AZ 用 mp.Pipe,Wire 类型差异是次要 follow-up,
     非本 change scope)。

PPO (本 session ship `provider_kwargs`) + DMC (golden inference_client pattern)
已 codify AB13 `actor_main` 双 escape hatch — AZ 是第三个 paradigm,本 change
让它复用 `inference_client` escape hatch (AZ 也用 InferenceClient → 与 DMC 同
一 dispatch path)。

cleanup risk medium:
- Production 路径切换比 PPO 大 (真有 MCTS selfplay logic 跑在 worker_loop 里),
  smoke_full 必跑保 zero regress;
- selfplay dispatch 语义 (round-robin game_idx) 与 actor_main 持续 episode loop
  有概念差,design.md D1 要给方案;
- Arena 是 **fully serial** (`arena.py` 0 mp,审计已确认 — 见下),所以 D2 不
  是 mp 迁移议题,而是 "什么也不动" 议题 — scope 收敛;
- AZ 暂不投 production training (Stage 3 pilot policy collapse,memory
  `project_stage3_pilot_policy_collapse_2026_05_28`),改造期不影响 in-flight run。

## 2. What

**5 part cleanup** (LOC budget ~ -250 net):

1. **新建 `training/paradigms/az/mp_factories.py`** (~ 240 LOC):
   仿 DMC `mp_factories.py` 模板,5 件套 + provider class:
   - `build_az_env_factory(cfg, seed)` — 用 `make_env_factory` 包 GicgEnv (复用
     现 `inference_worker.py:101-113` 的构造)。
   - `build_az_opp_registry(cfg)` — AZ selfplay 不真用 opp_registry (A5.2:
     both sides share network),但 protocol 要求,**返回 `OpponentRegistry` 注册
     单个 'self' fake handler** (raise on call,actor_main 不会真调它因为
     spec_sampler 不返 opponent_id ≠ 'self')。
   - `build_az_policy(cfg, actor_id)` — 复用现 `collector.py:_az_build_policy`
     返 `AZEpisodePolicy` (mcts_cfg + card_pool_spec)。
   - `build_az_provider(cfg, actor_id, *, inference_client)` — 显式 kwarg
     拿 InferenceClient,**通过 AB13 第 1 escape hatch (DMC pattern)**,
     返回 lightweight `_AZRemoteProvider` (持 inference_client + 透到
     `play_self_game`,client.request 路由到 server-side handle_eval_batch)。
   - `_az_spec_sampler(cfg, actor_id)` — 复用现 `collector.py:_az_spec_sampler`,
     selfplay-style EpisodeSpec (`opponent_id='self'`,`scenario_seed=derive_seed`)。

2. **重写 `training/paradigms/az/collector.py:AZAsyncCollector`** (~ -50 LOC):
   - 删 `_az_build_env_factory` / `_az_build_opp_registry` / `_az_build_policy` /
     `_az_build_provider` / `_az_spec_sampler` (搬 mp_factories.py)。
   - `__init__` 拿 `network` 后,在 `_bootstrap` 中**起 `InferenceServer` + 拿
     N `InferenceClient`** (复用 ParallelInferencePool 的 server 起法,即
     network_factory_path / inference_handlers_module_path 注入)。
   - `_bootstrap` 改 DMC 模板 `actor_kwargs_factory=lambda i: dict(base,
     inference_client=clients[i])`,dotted path 改指
     `training.paradigms.az.mp_factories.*`。
   - 不要 worker process 显式 dispatch (D1 推荐 B);actor_main 持续跑
     episode loop,trainer 拉 ring 直到拿到 `total_games` 个 episode 后 stop
     (失 game_idx 显式 numbering 但天然 sequencing via push order;
     AZ buffer ingest 不依赖 game_idx 值)。
   - 加 `n_games_remaining` 累 + `stop_event.set()` when reached (替代
     ParallelInferencePool 的 `dispatched_count() == consumed_count()` 终止
     条件)。

3. **删 `training/paradigms/az/inference_pool.py` (236 LOC) + `inference_worker.py`
   (156 LOC)** = -392 LOC:
   - `ParallelInferencePool` / `PoolDeadlock` / `WorkerError` / `worker_loop`
     全删 (功能由 Runtime + actor_main + AZAsyncCollector 覆盖)。
   - heartbeat / dispatch / round-robin / cmd_queue 全消失;PoolDeadlock 用
     `Runtime.actors_alive_count() < cfg.pipeline.num_actors` 替代 (D3 推荐 C)。

4. **改 `training/paradigms/az/train_loop/async_loop.py:run_async`**
   (从 `ParallelInferencePool` 切到 `AZAsyncCollector`,~ -40 LOC):
   - 删 `from training.paradigms.az.inference_pool import ...`。
   - 删 `pool.dispatch(game_idx=...)` for loop + `pool.next_result` ingest 循
     环 + `PoolDeadlock` handling。
   - 改成 `collector = AZAsyncCollector(cfg, pcfg, challenger, env_factory=None);
     collector._bootstrap(); ...; while result.n_games_played < config.n_games:
     out = collector.collect(...); ingest_trajectory(out, buffer, ...)`。
   - `pool.push_weights(...)` → `collector.sync_weights(challenger)`。
   - `pool.stats_queue` → 暂时 `None` (stats infra 由 InferenceServer 暴露,
     `_inference_server.stats_queue` access),`stats_ingest_loop` thread 改吃这个。
   - `pool.alive_workers()` → `collector.runtime.actors_alive_count()`(若 Runtime
     没暴露,新加 1 method)。
   - 这一步是本 change **最大 production-impact** 改动 — smoke_full 必跑保 zero regress。

5. **改 `training/paradigms/az/config.py:AZConfig`**:
   - `AZConfig.n_workers` (历史字段) 保留 (legacy run path 在用),但**让 `train_az`
     入口在调 `AZAsyncCollector` 前把 `cfg.n_workers` 写到 `cfg.pipeline.num_actors`**,
     unified pipeline 直接读 `cfg.pipeline.num_actors`。 即 `AZConfig.n_workers`
     成为 alias for `cfg.pipeline.num_actors` (legacy 名字保 train_az.py call
     site 不破),但 production 行为只看 pipeline 字段 (D5 推荐 hybrid)。
   - `AZParadigmConfig` 路径 (用于 unified driver via TOML `[paradigm.X.X]`):
     已经走 `cfg.pipeline.num_actors`,不动。

## 3. Affected specs

- `openspec/specs/training-architecture/actor-backend.md` — 待 D4 决策结果定:
  - **D4 选 (A)** (default,推荐):无 spec 改动,AZ 复用 AB13 第 1 escape hatch
    (`inference_client`,与 DMC 同 dispatch path)。
  - **D4 选 (B)**:加 AB14 codify "AZ selfplay 共享 InferenceServer + N
    InferenceClient pattern" (与 DMC 几乎重复,less recommended)。
  
  Spec patch file (`specs/training-architecture/spec.md`) 当前 placeholder,
  user 决 D1-D5 后再实质化。

## 4. Out of scope

- **不动** DMC / PPO / CFR / BC — 4 paradigm 不在本 change scope。
- **不改** `InferenceServer` 设计:`network_factory_path` +
  `inference_handlers_module_path` 已 paradigm-agnostic, AZ handlers
  (`_inference_handlers.py`) 不动。
- **不优化** MCTS / selfplay logic:`play_self_game` / `MCTSConfig` / `pool_spec.py`
  / `_az_losses.py` 一字不动。
- **不动** Arena (`arena.py` 150 LOC):**已审计确认 0 mp 路径** (全 serial,
  by design),本 change 与 arena 0 交集 (D2 推荐 — 见下)。
- **不换** Pipe → Socket inference wire:当前 `ParallelInferencePool` /
  `InferenceServer` 用 mp.Pipe (per-worker duplex)。DMC 用 TCP socket (R7
  post-I29 拓扑)。Wire type 切换是独立 perf-driven follow-up,**本 change
  保 Pipe** (zero behavior change on wire layer)。
- **不动** ckpt schema:AgentBase.save / load 不变。
- **不删** `inference_handlers.py`:AZ-shaped game_start + eval_batch handler
  本 change 保不变 (InferenceServer 端继续注入)。
- **不解** Stage 3 pilot policy collapse (memory
  `project_stage3_pilot_policy_collapse_2026_05_28`,与本 change 正交)。
- **不引入 `actor_backend='go'` 给 AZ**:AB3 status table 仍 AZ='不 support',
  Go port 是独立 ticket (Phase 2 follow-up)。
- **不强制 backwards-compat** for cfg loader:`AZConfig.n_workers` 字段保留
  当 legacy alias,unified pipeline 读 `cfg.pipeline.num_actors` (D5 选项 A
  hybrid)。

## 5. Decision summary (推荐方案 — see design.md D1-D5 全文)

- **D1 selfplay 推送语义**:推荐 **B (actor 连续 episode loop,trainer
  控制 stop_event)**。 主理由:与 actor_main 既有契约对齐 (DMC/PPO 已活),
  game_idx 显式 numbering 失但 push order 自然 sequencing,AZ buffer 不依赖
  game_idx 值。
- **D2 arena 二级 spawn**:推荐 **C (零迁,arena 保 serial)**。 主理由:
  audit 实测 `arena.py` 已 100% serial (无 mp,无 InferenceServer 复用),
  本 change scope 收敛,不增 risk。
- **D3 heartbeat / deadlock detection**:推荐 **C (删 heartbeat,用 Runtime
  actor alive count + stop_event timeout 替代)**。 主理由:MCTS rollout 长
  tail 在 actor_main 持续 episode loop 模式下天然每 episode boundary cancel
  point;Runtime.actors_alive_count 已等价 PoolDeadlock 检测。
- **D4 InferenceClient 字段复用**:推荐 **A (无 spec 改动,AZ 复用 AB13
  第 1 escape hatch)**。 主理由:AZ 与 DMC 同 inference_client 模式,AB13
  已 codify 该 path,新加 SHALL 是重复;若 future paradigm 需 differentiate
  再加 AB14。
- **D5 cfg shape**:推荐 **hybrid (legacy `AZConfig.n_workers` 字段保 alias,
  unified pipeline 读 `cfg.pipeline.num_actors`)**。 主理由:`train_az` 入
  口仍是 legacy run path 主入口 (production memory 引用),完全删 n_workers
  破 backwards;但 unified pipeline 字段是 ship-going-forward truth。 在 cfg
  入 driver 时 `cfg.pipeline.num_actors = cfg.n_workers` 一行 sync 即可。

**Effort**:~250 LOC net (+240 mp_factories.py +50 collector.py rewrite -392
inference_pool/worker -40 async_loop.py -10 config.py) + 4 OpenSpec artifact
~ 600 LOC。
