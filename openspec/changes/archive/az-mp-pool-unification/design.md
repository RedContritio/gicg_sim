---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: az-mp-pool-unification
---

# Design — AZ mp pool unification onto core/actor.actor_main + InferenceServer 收口

## 1. Goal

把 AZ 当前两条 mp 路径 (production `ParallelInferencePool` + unified driver
`AZAsyncCollector` stub) 收口到 **一条**:`AZAsyncCollector` 自己起
`InferenceServer` + N `InferenceClient`,actor 用 `Runtime + actor_main + SHMRing`
(DMC inference_client pattern),复用 AB13 第 1 escape hatch — 不增 spec SHALL。
production train_az 入口切走 ParallelInferencePool,unified driver 与 production
共用 AZAsyncCollector 唯一 mp pool。

## 2. Architecture context

### 2.1 现状 — AZ 两条 mp 路径并存

```
Path 1 (production):
[parent: train_az() → run_async()]
  ├─ ParallelInferencePool(config)
  │   ├─ InferenceServer(n_workers=N, network_factory_path='az.network.Agent',
  │   │                  inference_handlers_module_path='az._inference_handlers')
  │   │   └─ mp.Pipe duplex per-worker (server_end ↔ client_end)
  │   ├─ N worker mp.Process(target=worker_loop)
  │   │   ├─ InferenceClient(worker_id, server_pipe)
  │   │   ├─ heartbeat thread (heartbeat_ts shared mp.Array,2s tick)
  │   │   └─ cmd_queue.get loop:
  │   │       cmd['kind']='play' → play_self_game(client, env, ...) →
  │   │         result_queue.put(SelfPlayResult)
  │   ├─ dispatch(game_idx, env_seed) → round-robin cmd_queue.put
  │   ├─ next_result() → result_queue.get + PoolDeadlock detect via alive_workers
  │   ├─ push_weights → server.push_weights → weight_queue (server-side load)
  │   └─ atexit + sigterm cleanup
  ├─ for game_idx in range(N_games): pool.dispatch(game_idx, ...)
  └─ ingest_thread: while < n_games: pool.next_result() → ingest_trajectory(buffer)

Path 2 (unified driver, stub):
[parent: tools.runs.train → driver → AZParadigm.make_collector → AZAsyncCollector]
  ├─ Runtime(cfg) (WeightsSHM + ActorProcess pool)
  ├─ SHMRing(capacity=1024)
  ├─ runtime.publish_weights(sd_cpu, version=0)
  ├─ runtime.start_actors(N, actor_kwargs_factory=...) → actor_main
  │   ├─ build_env_factory_path = '...collector._az_build_env_factory'
  │   ├─ build_provider_path = '...collector._az_build_provider'
  │   └─ spec_sampler_path = '...collector._az_spec_sampler'
  └─ collect(): ring.try_pop loop (stub: trajectories=[(None, item)])
  
  ⚠ NO InferenceServer here — provider 怎么拿网络是空白 (stub-shape)。
  ⚠ docstring 直说 "End-to-end production still requires AZ migration off
    play_self_game onto typed EpisodePolicy"。
```

两条路径互不知道对方;production train_az 走 Path 1,unified driver 走
Path 2;Path 1 不接 core/actor (复制 ~ 392 LOC infra),Path 2 不接
InferenceServer (无完整 production loop)。

### 2.2 目标 — 收口到一条 AZAsyncCollector

```
[parent: AZAsyncCollector._bootstrap (shared by train_az + unified driver)]
  ├─ Runtime(cfg) (WeightsSHM + ActorProcess pool)  ← 既有
  ├─ SHMRing(capacity=1024)  ← 既有
  ├─ runtime.publish_weights(sd_cpu, version=0)  ← 既有
  ├─ self._inference_server = InferenceServer(  ← NEW (从 ParallelInferencePool 搬)
  │     agent_config=cfg.agent,
  │     n_workers=N,
  │     network_factory_path='training.paradigms.az.network.Agent',
  │     inference_handlers_module_path='training.paradigms.az._inference_handlers',
  │   )
  │   server.start()
  ├─ self._inference_clients = [
  │     InferenceClient(worker_id=i, pipe=server.get_worker_pipe(i))
  │     for i in range(N)
  │   ]  ← NEW (从 ParallelInferencePool 搬)
  └─ runtime.start_actors(  ← 已 stub,改 mp_factories.* + inference_client
       N=cfg.pipeline.num_actors,
       actor_kwargs_factory=lambda i: dict(
         build_env_factory_path='training.paradigms.az.mp_factories.build_az_env_factory',
         build_opp_registry_path='training.paradigms.az.mp_factories.build_az_opp_registry',
         build_policy_path='training.paradigms.az.mp_factories.build_az_policy',
         build_provider_path='training.paradigms.az.mp_factories.build_az_provider',
         spec_sampler_path='training.paradigms.az.mp_factories.az_spec_sampler',
         inference_client=self._inference_clients[i],  ← AB13 第 1 escape hatch
         transition_queue=self.ring,
         push_episode_record=False,  # AZ trajectory 自带 game_static + steps
                                      # via record.transitions[*].payload
       ))

[child: actor_main spawn]
  ├─ build_provider(cfg, actor_id, inference_client=client)
  │   → _AZRemoteProvider(cfg, actor_id, client=client)
  │     └─ provider 提供 game_start / eval_state 接口给 selfplay
  ├─ env_factory builds GicgEnv per episode
  ├─ policy = AZEpisodePolicy(mcts_cfg, card_pool_spec)
  ├─ runner = EpisodeRunner(env_factory, opp_registry)
  └─ while not should_stop():
       spec = az_spec_sampler(cfg, actor_id)  # selfplay,opp_id='self'
       record = runner.run(spec, policy, provider)
       transition_queue.push(record.transitions)  # ring push
       provider.update_weights()                    # poll new weights
```

InferenceServer 端的 mp.Pipe wire / batched forward / handle_eval_batch 完全
不动,只是起的地方从 ParallelInferencePool 搬到 AZAsyncCollector。

### 2.2-CORRECTION (2026-05-29 T1 forensic — D1 改 B')

上方 child-spawn 框图 (line 100-104) 的 `EpisodeRunner.run(spec, policy, provider)`
→ `AZEpisodePolicy.act` 路径**前提错误**,实读代码证伪两点:

1. **EpisodeRunner 无 opp_id=='self' short-circuit**:`episode_runner.py:58` 无条件
   `opp = opponent_registry.get(spec.opponent_id)` + 对手回合 `opp.select_action(env)`
   (line 103)。AZ selfplay 两侧需同一网络 (经同一 InferenceClient),但
   `OpponentRegistry` factory 只收 `(seed, params)`、`build_az_opp_registry` 只收
   `cfg` —— 都拿不到 provider/client,对手侧无法驱动。
2. **AZEpisodePolicy.act 非 production-wired**:`act` 要求 obs 是带 `env` /
   `viewing_player` 的 dict (MCTS determinize 需 env),但 `EpisodeRunner._get_obs`
   返回裸 numpy → act 直接 raise。policy docstring 自承该 protocol-act 路径
   "only wired for tests","serial AZ 走 play_self_game"。

根因:AZ selfplay (双边 + MCTS + 共享网络) 不匹配 EpisodeRunner 的单边 episode
模型 —— 与 CFR traversal 同类。**修正 (B')**:用 AB14 `episode_runner_factory`
(CFR 已 ship 的 hatch) 插入 paradigm-local `AZSelfPlayRunner`,其 `run(spec,
policy, provider)` 内部调**现有 `play_self_game(evaluator=provider, env, ...)`**
(provider = `_AZRemoteProvider`,暴露 game_start/eval_state)。policy + opp_registry
被 runner 忽略 (同 CFRTraversalRunner),仅 stub 满足 actor_main 非空校验。

收益:复用 proven `play_self_game` selfplay 逻辑 (selfplay 正确性不变,只换 mp
编排);绕开 EpisodeRunner/obs 两个 blocker;`play_self_game` 输出 = 现
ParallelInferencePool 的 SelfPlayResult (game_static + steps + winner) → T5
ingest_trajectory 比原计划更接近现 contract。actor 端 child-spawn 实为:

```
[child: actor_main spawn]
  ├─ build_provider(cfg, actor_id, inference_client=client) → _AZRemoteProvider
  ├─ build_policy → AZ stub policy (unused, satisfies actor_main 校验)
  ├─ build_opp_registry → empty/stub (unused — selfplay 不查 registry)
  ├─ episode_runner_factory=build_az_selfplay_runner → AZSelfPlayRunner (AB14)
  └─ while not should_stop():
       spec = az_spec_sampler(...)        # opponent_id='self' (decorative)
       output = AZSelfPlayRunner.run(spec, policy, provider)
                  └─ play_self_game(evaluator=provider, env=env_factory(seed), ...)
       transition_queue.push(output)      # SelfPlayResult-shape payload
       provider.update_weights()
```

下方 §3 D1 的 "推荐 B" 升级为 **B'**:保留 B 的 "actor 连续 loop + trainer
stop_event 控" 控制流,但 lifecycle 经 AB14 AZSelfPlayRunner (非 EpisodeRunner)。
§4 (D2 arena) / §5 (D3 heartbeat) / §6 (D4 cfg) / §7 (D5) 不受影响。后续 task
(T1 build_az_selfplay_runner + stub policy/opp;T2 collector actor_kwargs 加
episode_runner_factory_path + push_episode_record=True;T5 ingest 读
SelfPlayResult payload) 按 B' 调整。

### 2.3-CORRECTION-2 (2026-06-01 T4 dead-stack 审计 — 方向 C:废 legacy 全删)

T4 production-path 审计(实读 `tools/runs/_train/dispatch.py` + `paradigm.py:98-118`
+ 全仓 grep + Explore dead-code 边界审计)证实:**production `tools.runs.train`
完全不经过 legacy 栈**。统一 pipeline `run_pipeline` → `AZParadigm.make_collector`
→ `cfg.pipeline.mode=='async'` 时 `AZAsyncCollector`(`_async.py`,T1/T2 已 ship)/
serial 时 `AZSelfPlayCollector`。legacy 入口 `train_az() → run_async()
(async_loop.py) → ParallelInferencePool(inference_pool/worker)` 是**独立 dead 栈**,
唯一非-test 消费者是 `tools/profile/*` 2 脚本。

**对原 B' 的修正**:原 §3-下 T3-T8 计划「改 `async_loop.py:run_async` 接
AZAsyncCollector + 改 `helpers.py:ingest_trajectory` contract」**前提失效** ——
run_async 是 dead 入口,改它是给死代码做手术,无 production 价值。§12 原 acceptance
gate 列的「train_az full lifecycle smoke_full」当 production gate **也是错的**
(production 不走 train_az)。

**方向 C 决策(替换原 B' 的 T3-T8)**:废弃整条 legacy 栈,全量删除(per 工作风格
「废弃子系统时全量删除,不留并行栈 / 迁移垫片」)。删除边界经 dead-code 审计确定:

**DELETE(纯 dead)**:
- `train_az.py`
- `train_loop/` 整个子包(`__init__` / `async_loop`[run_async] / `helpers` /
  `run_result` / `stats_ingest`)—— production 仅 docstring 提及,零 import
- `inference_pool.py` + `inference_worker.py`
- `config.py`:`AZConfig` + `smoke_config`/`fixed_1v1_config`/`random_1v1_config`
  (**部分删除**,保留 `AZParadigmConfig`/`MCTSCfg`/`TrainStepCfg`/`AgentShapeCfg`
  + 清理随之 unused 的 imports + `__all__` 条目)
- guard tests:`test_train_az` / `test_parallel_inference` /
  `test_parallel_pool_deadlock` / `test_az_champion_path` /
  `test_az_train_az_phase2_path` / `test_az_inference_phase2_path` /
  `test_az_config_train_loop_phase2_zeta`
- **`arena.py` + `config_loader.py`** (2026-06-01 核查纠正,原标 KEEP — grep 证伪):
  - `arena.py` — 删 `train_loop/` 后非-test 引用归零 (`maybe_arena` / `arena_match` /
    `ArenaResult` 全在 `train_loop/` 的 helpers / async_loop / run_result);
    **champion-vs-challenger self-arena 机制随 legacy 退役**,统一 pipeline 用 periodic
    gauntlet eval 替代。连 `test_arena.py` + `test_az_arena_phase2_path.py` 删。
  - `config_loader.py` — import 被删的 `AZConfig` + presets (删后必 import error);
    legacy AZ TOML loader,production 走 `core/config/loader.py:load_cfg`。连
    `test_config_loader.py` 删 + 清 `az/__init__.py` re-export + phase3c allowlist +
    核查 `tools/eval/_paradigm.py` AZ reserved slot。

> **边界判断教训**:审计 agent 的「KEEP-for-now / 避免 scope creep」太保守,与工作风格
> 「废弃子系统全量删除 / dead defensive code 必删」冲突。删 legacy 后变 dead 或依赖被删
> symbol 的文件,应一并删,不留「以防万一」。

**KEEP(SHARED)**:
- `pool_spec.py` —— 被 `collector`/`paradigm`/`mp_factories` 引用,**不删**,只摘掉
  `inference_worker` 那个 caller(随 inference_worker 一起没)
- `selfplay.py` / `determinize.py` / `train_step.py` / `mp_factories.py` /
  `_player_loader.py` —— 统一 pipeline 锚点

**Scope 决定(user 2026-06-01,3 问)**:
1. **async verify = serial verify + async follow-up**:本 change acceptance 收敛到
   serial 路径(统一 pipeline serial collector + AZ smoke);AZ async e2e verify 依赖
   `pipeline-async-weight-sync` change 的 weight-sync fix(否则 async actor 永用
   version-0 权重 — 即 run 149 collapse 疑因),作 follow-up 挂该 change ship 之后。
2. **profiling = 迁移到统一 pipeline 入口**:`tools/profile/{profile_parallel,
   profile_smoke}.py` 改调 `tools.runs.train` / run_pipeline + AZ cfg
   (`num_actors` 替 `n_workers` / `mode=async|serial`)。
3. **config 边界 = 一并全删 + 全迁移**:删 config.py `AZConfig`+presets,迁移全部
   连锁消费者 —— 6 production-adjacent tests(`test_eval_service_*` /
   `test_core_eval_baselines` / `test_gauntlet_path` / `test_scenario_sampling`)
   + 5 `tools/debug/*` + 2 profile 的 fixture 到 `AZParadigmConfig` / 新 fixture,
   并改 `test_production_tests_az_refs_phase3{c,d}` 的硬编码 allowlist。

§3 D1(B')/§4-§7(D2-D5) 不变 —— 它们描述统一 pipeline collector wiring,已 T1/T2
ship。本 CORRECTION-2 只废 legacy 栈 + 修正 §12 acceptance(下方 §12 同步改)。

## 3. Decision D1 — Selfplay 推送语义

AZ 当前 `ParallelInferencePool` 通过 `dispatch(game_idx, env_seed)` 显式按需
推 game,worker pull → run → push result。 round-robin scheduling,主进程
显式控制 dispatch count。 `actor_main` 是持续 episode loop (DMC/PPO 已活)。

### 方案

**(A) 保持 dispatch 显式 — actor_main 扩支持 WorkItem queue**:
- actor_main 加新参数 `dispatch_queue: Optional[mp.Queue] = None`,
  若给则 episode loop 改 `cmd = dispatch_queue.get()` 替代 spec_sampler。
- 优点:零 production 行为变化 (game_idx 完全显式)。
- 缺点:加 actor_main signature (与 paradigm-agnostic 原则有摩擦);DMC/PPO
  不用 dispatch_queue 字段闲置;test 要 cover 两种调度路径;与 actor_main
  既有 "spec_sampler 决定每 episode" 模型冲突。

**(B) actor 连续 episode loop,trainer 控制 stop_event** (推荐):
- 删 dispatch — actor 持续跑 episode (每 episode 内部 az_spec_sampler 出新
  seed),ring 顺序自然 sequencing。
- `run_async` 改 `while result.n_games_played < config.n_games: drain ring`,
  收齐后 `stop_event.set()` → actor 下一 episode 前 should_stop() 返 True →
  退出。
- 优点:与 actor_main 既有契约对齐 (零 signature 改动);与 DMC/PPO 同
  pattern (collect-driven control loop);删 cmd_queue / round-robin / dispatch
  / dispatched_count 整套 ~ 50 LOC。
- 缺点:游戏 numbering 不再显式 (但 AZ buffer ingest 只用 winner + transitions,
  不依赖 game_idx 数字);N games per actor 不严格平均 (但
  bench-equivalent — 各 actor 抢 ring,产出端 deterministic by spec_sampler
  seed sequence)。
- 风险点:`config.n_games` 达成时 actor 可能仍有 in-flight episode (跑到一半
  push 不进 ring 因为 collect 已停);mitigation:`should_stop()` 检在每
  episode 起点 (现 actor_main 行为),允许 final-in-flight finish + push,
  trainer 多 drain 一次。

**(C) 不走 actor_main — Runtime.start_actors(target=az_selfplay_main)**:
- 复用 Runtime + WeightsSHM + sigterm 但 actor entry function 是
  paradigm-local `az_selfplay_main`,内部跑 dispatch_queue.get + play_self_game。
- 优点:production selfplay 语义 1:1 保留;不强 actor_main 接 dispatch。
- 缺点:**违反 backlog #88 主目标** (统一到 actor_main);留两套 actor entry
  长期维护 burden;失 actor_main 的 EpisodeRunner / opp_registry / build_policy
  / spec_sampler 5 件套结构。

### 推荐 B (~ +0 / -50 LOC,与 actor_main 既有契约对齐)

actor 持续 episode loop,trainer side 收齐 n_games_played 后 stop_event.set。
AZ buffer ingest 已经只看 `record.winner` + `record.transitions`,game_idx 数
字 numbering 不是契约一部分。 缺 final-in-flight cleanup → 加 `collect` 多一
次 drain 即 OK。 D1 选 B 即让 backlog #88 完成 (所有 5 paradigm actor 都走
actor_main)。

## 4. Decision D2 — Arena 二级 spawn

### Arena.py audit 结果 (实读 `training/paradigms/az/arena.py` 150 LOC)

```python
# arena.py:34
def arena_match(challenger, champion, env_factory, n_games, *,
                max_game_steps, seed, mcts_config, card_pool_spec):
    rng = random.Random(seed)
    for g in range(n_games):
        env = env_factory(g)
        winner = _play_one(env=env, p0_agent=..., p1_agent=..., ...)
        ...

# arena.py:89
def _play_one(*, env, p0_agent, p1_agent, max_game_steps, rng,
              mcts_config, card_pool_spec) -> int:
    p0_agent.game_start(env.static_obs)
    p1_agent.game_start(env.static_obs)
    while env.phase == 1: env.step(0)
    for step_idx in range(max_game_steps):
        if env.done: return env.winner
        acting = env.acting_player
        agent = p0_agent if acting == 0 else p1_agent
        if use_mcts:
            from training.paradigms.az.mcts import mcts_search
            action_idx, _ = mcts_search(env, agent, card_pool_spec, rng, ...)
        else:
            prior, _value = agent.eval_state(dyn_obs, refs, payments)
            action_idx = int(np.argmax(prior))
        env.step(action_idx)
    ...
```

**Audit 结论**:`arena_match` + `_play_one` 是 **100% 单进程 serial loop**:
- 0 `mp.Process` / `mp.Queue` / `mp.Pipe` / `InferenceServer` 调用。
- 0 worker pool / dispatch / heartbeat。
- challenger / champion `agent.eval_state` 直接 in-proc forward (`agent` =
  `Agent` 实例,持自己 net + device,zero inference server)。
- 顺序循环:`for g in range(n_games): _play_one(...)`,无并行。

Arena 在 `run_async` 里被调用方式 (`train_loop/helpers.py:maybe_arena`,
未读但符合 `state_lock` 同步语义):**main thread 拿 `state_lock` 后调
`arena_match`**, blocks 整 train loop until done。 即 arena 与 train + selfplay
完全 serial mutex,无并发对 InferenceServer 的竞争。

### 方案

**(A) 本 change 同时迁 arena pool**:
- 让 arena 复用 selfplay 的 N InferenceClient + actor pool 跑并行 arena game。
- 优点:n_games_per_arena × 2-agent eval 加速 N 倍。
- 缺点:**不必要 scope 扩** — arena 当前不在 production hotpath (only fires
  每 ~ 100 games once),N=1 actor 也能跑完 ~ 40 game arena 在 minutes 级,不
  block train loop。 challenger / champion 两 agent 用同一 InferenceClient
  pool 有 weight version 互斥问题 (challenger 用 latest, champion 用 snapshot;
  server 只持 latest);需重设计 inference handler 区分 agent — 非本 change scope。

**(B) Arena pool 不迁 (留独立 mp 路径)**:
- 不存在该路径 (arena 0 mp,已 audit)。

**(C) Arena 改 serial (在 trainer 主进程跑)** (推荐):
- 现状即如此 — 0 LOC 改动。 challenger / champion 在 main thread 直接
  `agent.eval_state` (in-proc forward),与 InferenceServer 完全无 overlap。
- 优点:零迁,scope 收敛;arena correctness 不受 mp 迁移影响 (并发 bug
  surface 0);若 future arena perf 成 bottleneck 可独立 change 处理。
- 缺点:arena run wall_s 大 (40 game × ~ 200ms each = ~ 8s 与 train block);
  但 production 数据 `gauntlet_games_per_opponent=20` + arena `n_games=40`
  量级,arena 频率 100 game one-shot,占 train wall 比 < 1%。

### 推荐 C (零迁,arena 保 serial)

audit 已确认 arena 100% serial,本 change 不动 arena.py / helpers.py。 arena
mp 化是独立 backlog (perf-driven,not architectural-driven),与 backlog #88
统一目标无重叠。 spec 也不增 SHALL。

## 5. Decision D3 — Heartbeat / deadlock detection

### 现状

`ParallelInferencePool._HEARTBEAT_THRESHOLD_S=10s` + `PoolDeadlock`:
- worker_loop 起 `_heartbeat_loop` thread 每 2s 写 `heartbeat_ts[wid] = time.time()`
- `alive_workers()` 算 `now - heartbeat_ts < 10s`
- `next_result(timeout)` 若 `result_queue.empty` + `alive_workers < N` +
  `dispatched > consumed` → raise `PoolDeadlock`

机制存在原因:MCTS rollout 长 tail (n_rollouts=200 + 复杂 env state) 单
episode 可跑 10s+,而 worker process 死了 (cgo segfault / OOM / SIGKILL by OS)
不会通知 main,deadlock 无穷等。 DMC/PPO actor 每 episode 短 (~ ms-级),
worker 死了下次 `proc.is_alive()` 即检出,不需 heartbeat tier。

`actor_main` 当前等价机制:
- `Runtime` 持 `ActorProcess` list (`actor_process.py:241+`),每个有 `is_alive()`。
- `Runtime.start_actors` 后 user 可 poll `actor.is_alive()` 检 dead worker。
- 但**无 N → trainer 通知机制**:trainer 一直 `ring.try_pop` 不会因 actor 死
  早 fail (ring 空 == 无 push == 无 actor 跑)。

### 方案

**(A) 加 actor_main level heartbeat thread**:
- core/actor 加 `Runtime.spawn_heartbeat_monitor(threshold_s)` 共享机制,
  每 actor 起 heartbeat thread (mp.Array<float>),Runtime side 提供
  `actors_alive_count()`。
- 优点:所有 paradigm 受益 (future DMC long episode 也可用)。
- 缺点:对 DMC/PPO over-engineering (它们 actor short episode 已 fine);
  spec 加 AB14 / AB15;LOC 增加 core/。

**(B) AZ-local heartbeat in mp_factories.py**:
- mp_factories.py wrap actor_main 加 heartbeat thread。
- 但 actor_main 是 `target=actor_main`,wrapping 需要新 entry function
  → 又回到 D1 (C) 路径 = 不走 actor_main。 矛盾。
- 或:在 `_AZRemoteProvider.observe_env` hook 加 `_az_heartbeat_ts[actor_id]
  = time.time()`,trainer 端 poll mp.Array (paradigm-local mechanism)。
  cleaner 但仍 +50 LOC。

**(C) 删 heartbeat,用 Runtime.actors_alive_count + stop_event timeout 替代** (推荐):
- 把 actor crash 检测交给 OS:`Runtime.actors_alive_count()` 比较 `cfg.pipeline.num_actors`,
  少则 raise (新加 1 method)。
- `collect` 主循环加 `if alive < N and ring.empty(): raise WorkerError`。
- MCTS 长 tail 不再特殊处理 — 单 actor 跑 1 episode 10s+ 但仍 alive,collect
  blocks 在 `ring.try_pop` 直到 episode done,正常。 actor 真死了 (OS-level)
  → `proc.is_alive()` 立即返 False。
- 优点:零 actor side state (heartbeat thread 删);spec 不加 SHALL;与
  DMC/PPO 同 detection model。
- 缺点:cgo hang (Go runtime infinite loop) 不会触发 `is_alive=False` —
  process 还活,只是不响应。 但本 change scope 不涉及 cgo (AZ 当前 pure
  Python MCTS 跑 in worker process,Go MCTS 是独立 backend 选项 `cfg.mcts.backend='go'`,
  hang 可能性低)。

### 推荐 C (零 spec 改动,与 DMC/PPO 同 model)

删 heartbeat → 用 Runtime.actors_alive_count + `is_alive()` 替代。 删除
overhead:`ParallelInferencePool` heartbeat code -30 LOC + worker_loop
heartbeat thread -10 LOC。 若 future AZ 跑大量 cgo MCTS (backend='go')
+ hang 成 production 问题,**单独 follow-up backlog**:加 cooperative
cancellation token (cgo-side `runtime.Gosched` + ctx.Done() 检) 而非加 heartbeat
band-aid。

## 6. Decision D4 — InferenceClient 字段复用

PPO change 加 AB13:`provider_kwargs` (PPO pattern) 与 `inference_client`
(DMC pattern) 互斥 escape hatch。 AZ 用真 `InferenceClient` (worker 通过
client.request 调 server-side forward),与 DMC 同 dispatch path。

### 方案

**(A) 保持 AB13 现状,AZ 走 inference_client (与 DMC 同 path)** (推荐):
- 无 spec 改动。
- `build_az_provider(cfg, actor_id, *, inference_client)` 签名与
  `build_dmc_provider(cfg, actor_id, *, inference_client)` 一致。
- AB13 文字已 cover ("DMC pattern, parent-constructed InferenceClient handle
  attached to shared InferenceServer") — AZ 是该 pattern 第二个用户。

**(B) AB14 codify "AZ selfplay 共享 InferenceServer + N InferenceClient"**:
- 把 AB13 扩成 AB13a (inference_client 通用 spec) + AB13b (specifically
  selfplay 模式 — N=2 agent 共用一个 server,但 selfplay 两 side 是同 net
  所以 OK)。
- 缺点:与 DMC 几乎重复 (差异是 SelfPlay vs 异 net opponent,但 InferenceServer
  仍 1 net);spec 膨胀无 net 信息增益;future paradigm 加 mp 不会因 AB14
  受益 (信息已在 AB13)。

### 推荐 A (无 spec 改动)

AB13 第 1 escape hatch 直接 cover AZ;`spec.md` placeholder 直接写 "no spec
change required — AZ reuses AB13 inference_client escape hatch"。 spec patch
file 简洁,不增 SHALL noise。

## 7. Decision D5 — cfg shape

AZ 当前两套 cfg:
- `AZConfig.n_workers` (历史字段,`AZConfig(TrainingConfig)` 继承,
  `train_az` legacy path 用)。
- `AZParadigmConfig` (无 n_workers,unified driver 通过 `cfg.pipeline.num_actors`
  读)。

`AZAsyncCollector` 当前 (unified path) 已读 `cfg.pipeline.num_actors`
(`collector.py:243`)。

### 方案

**(A) 统一到 `cfg.pipeline.num_actors` (PPO/DMC 标准),deprecate
`AZConfig.n_workers`**:
- 删 `AZConfig.n_workers` 字段。
- `train_az.py` legacy 入口加 deprecation:cfg load 时若有 `n_workers` 写
  warning + 写到 `cfg.pipeline.num_actors` (但 `AZConfig` 现没 pipeline 字段...);
- 实际上 `AZConfig` 不继承 unified `Config`,没有 `cfg.pipeline`,需要给它
  加 `pipeline: PipelineConfig` 字段 → 大改造 (legacy cfg dataclass 兼容
  断)。
- 缺点:破 legacy `train_az` 入口的所有 production cfg 文件 (configs/az/*.toml
  的 `n_workers = N` 字段) → backwards-compat break。

**(B) 不迁,继续读 `cfg.n_workers`** (legacy path) + `cfg.pipeline.num_actors`
(unified path):
- 不一致但 less break。
- 缺点:future bug surface (两个字段 source of truth 漂移)。

**(C) Hybrid — `AZConfig.n_workers` 保留 (legacy alias),unified pipeline 读
`cfg.pipeline.num_actors`,在 cfg 入 driver 时 sync `cfg.pipeline.num_actors =
cfg.n_workers`** (推荐):
- `AZConfig` 字段不动 (legacy cfg 兼容)。
- `AZAsyncCollector._bootstrap` 一行 `n_actors = int(getattr(self.cfg.pipeline,
  'num_actors', None) or getattr(self.cfg, 'n_workers', 1))` (graceful
  fallback)。
- `train_az.run_async` 入口加 1 行:`if hasattr(config, 'pipeline') and not
  config.pipeline.num_actors: config.pipeline.num_actors = config.n_workers`
  (但 `AZConfig` 没 pipeline 字段,需小 patch:`AZConfig` 加 optional
  `pipeline: Optional[Any] = None` for forward-compat,sync 时 lazy 建)。
- 优点:zero break;两套 cfg path 都 work;future 迁全 unified 时一行删 alias
  即可。
- 缺点:轻微复杂 (两个字段共存)。

### 推荐 C (hybrid,保 backwards-compat)

D5 选 C 不会让 production cfg.toml 文件失效。 完整 unified 迁是独立 backlog
(`AZConfig → AZParadigmConfig 一体化`,与 backlog #88 正交)。

## 8. PPO change 沿用 vs AZ-specific 差异

| Aspect | PPO change (已 ship) | AZ change (本 change) |
|---|---|---|
| escape hatch | `provider_kwargs` (新加 AB13) | `inference_client` (AB13 既有) |
| spec patch | ADD AB13 | NO ADD (reuse AB13) |
| Old mp code 删 | env var hack + tempfile pickle helpers ~ 130 LOC | ParallelInferencePool + worker_loop ~ 392 LOC |
| New mp_factories.py | ~ 160 LOC | ~ 240 LOC (provider 多了 InferenceClient handling) |
| 主入口改动 | _async.py 缩到 150 LOC | async_loop.py 切到 AZAsyncCollector ~ -40 LOC |
| 新增 InferenceServer 起的地方 | 无 (PPO 用 LocalNetworkProvider + WeightsSHM) | AZAsyncCollector._bootstrap (从 ParallelInferencePool 搬) |
| cfg 改 | 不动 (PPO 已用 `cfg.pipeline.*`) | hybrid `n_workers` ↔ `pipeline.num_actors` |
| 算法 logic 改 | 0 | 0 (selfplay logic / MCTS 不动) |
| Test 改 | unit + 1 smoke_full | unit + 1 smoke_full + production selfplay smoke (train_az + N=2 + 5 game) |

## 9. 关键 invariant 改动

### 9.1 spec.training-architecture/actor-backend.md

**推荐 D4 (A) → 无 spec 改动**。 `spec.md` patch 文件写:

> `# No spec change required — AZ reuses AB13 inference_client escape hatch
> (DMC pattern). Code refs add AZ entries in actor-backend.md § 4 (live spec)
> upon implement, not in this change patch.`

Live spec `actor-backend.md` § 4 (Code references) 在 implement 阶段加 AZ
entries (mp_factories / AZAsyncCollector / mp e2e test);本 change DRAFT phase
不动 live spec。

### 9.2 InferenceServer 接 paradigm — 保不变

`InferenceServer(network_factory_path=..., inference_handlers_module_path=...)`
W2-1/W2-2 已 paradigm-agnostic, AZ 继续注 `network.Agent` +
`_inference_handlers`;本 change 0 server 改动。

## 10. Out-of-scope decisions

- **不引入 socket TCP wire** (DMC R7 pattern):AZ `ParallelInferencePool` 用
  mp.Pipe,本 change 保 Pipe (zero wire change)。 socket 切换是 perf-driven
  follow-up,与 backlog #88 正交。
- **不动 ckpt schema**:AgentBase.save / load 不变。
- **不引入 actor_backend='go'** for AZ:Phase 2 follow-up (memory
  `project_i29_complete_redesign_pivot` Go MCTS pending)。
- **不解 Stage 3 policy collapse**:与本 change 正交。
- **不优化 MCTS rollout / determinize / selfplay logic**:0 改动到
  `selfplay.py` / `mcts/*` / `determinize.py`。

## 11. Risk

1. **D1 (B) actor 持续 episode loop 风险 — final-in-flight episode 漏 push**:
   actor 跑到一半 trainer 已 `stop_event.set()`,actor episode 跑完 push ring
   时 collect 已退出,ring 永远不被 drain。
   - mitigation:collect 主循环 `while self.runtime.actors_alive_count() > 0
     or self.ring.try_pop() is not None: ...`,actor exit 后再 drain 一次。
   - e2e test 验:`collect_count_total >= n_games_dispatched` (放宽 — actor
     可能 over-shoot;但不会 under-shoot)。

2. **InferenceServer 在 AZAsyncCollector 起,与 production train_az 同一
   process — atexit / sigterm 二级 cleanup 顺序**:
   `ParallelInferencePool` 已经 atexit + sigterm signal handler 做 cleanup;
   AZAsyncCollector 通过 Runtime 应该等价,但 Runtime sigterm install_quiet_sigterm
   在 child end,parent end 需要 self-managed cleanup。
   - mitigation:`AZAsyncCollector.close` 显式 `inference_server.stop()` +
     `inference_clients[*].close()` + `runtime.close()` + `ring.close()`,
     顺序与 DMC `_bootstrap` close path 一致 (`collector.py:288-`)。
   - test 验:`test_az_async_collector_close_no_leak.py` — 5 ep + close
     + `ps grep python` confirm 无 dangling worker / server。

3. **AZ buffer.append 与 ring push contract**:
   `ParallelInferencePool` push `dict` (game_idx / steps / winner / ...);
   `AZAsyncCollector + actor_main` push `record.transitions` (list[Transition]) or
   full `EpisodeRecord`。 schema 差异 → buffer ingest 改 (helpers.py `ingest_trajectory` 签名)。
   - mitigation:实现阶段 read `helpers.py:ingest_trajectory`,改其 input
     contract 与 EpisodeRecord 适配 (winner + transitions list);async_loop.py
     调用点同步改。 这是 ~ 50 LOC 改动,scope-bounded。
   - test 验:`test_ingest_trajectory_episode_record.py` verify 新 contract。

4. **`cfg.pipeline.num_actors` vs `cfg.n_workers` 字段漂移 (D5 hybrid)**:
   train_az 入口 sync 若漏一个 path → actor count 0 or wrong。
   - mitigation:`AZAsyncCollector._bootstrap` 显式 raise if `n_actors <= 0`,
     loud fail。 单元 test cover both cfg paths。

5. **InferenceServer 起 N worker pipe vs `Runtime.start_actors(N)` 拓扑对齐**:
   `InferenceServer(n_workers=N)` pre-allocates N server-side pipe ends;
   `Runtime.start_actors(N)` spawn N actor。 N 一致是契约,actor 拿
   `inference_clients[i]` 时 i ∈ [0, N),不可越界。
   - mitigation:`_bootstrap` 显式 assert `len(self._inference_clients) ==
     n_actors`,raise on mismatch。

## 12. Acceptance gate (方向 C — 见 §2.3-CORRECTION-2)

**本 change (serial verify + legacy 全删)**:
- `pytest -n 4 training/tests/test_az_*.py -q` 全 PASS (迁移后 fixture 无 regress)。
- grep legacy 删尽:`train_az` / `run_async` / `ParallelInferencePool` /
  `inference_pool` / `inference_worker` / `train_loop` / `AZConfig` /
  `smoke_config` / `fixed_1v1_config` / `random_1v1_config` 在
  `training/` (非 archive) + `tools/` 0 import hit (仅允许 docstring/注释残留经
  human review)。
- `pytest -m smoke training/tests/ -q -k az` 全 PASS (serial 统一 pipeline 路径)。
- 迁移消费者全过:6 production-adjacent tests + 5 `tools/debug/*` + 2 profile
  脚本改 `AZParadigmConfig` / 统一 cfg 后可跑 (profile 脚本 smoke import + 单步)。
- `test_production_tests_az_refs_phase3{c,d}` allowlist 改后 PASS (无 stale 条目)。
- ruff format clean + line limit hooks 全 pass (删文件后无新 violator)。

**async e2e (follow-up,非本 change gate)**:
- `test_az_async_collector_e2e.py` (smoke_full,2-actor 真 spawn + InferenceServer
  + N=2 worker + 5 episode + clean shutdown + deterministic by seed) 挂
  `pipeline-async-weight-sync` change ship 之后 (需 weight-sync fix 才能验 actor
  收到 weight version bump;否则 async actor 永用 version-0 权重)。
