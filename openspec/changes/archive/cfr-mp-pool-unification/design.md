---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: cfr-mp-pool-unification
---

# Design — CFR mp pool unification + 4 lifecycle 决策

## 1. Goal

把 `ParallelCFRTrainer` (`parallel_trainer.py` 170 LOC) + `cfr_worker_main`
(`worker.py` 203 LOC) 完全 collapse 到 `core/actor.Runtime + actor_main +
mp_factories` 模板,与 DMC (`paradigms/dmc/`) + PPO (`paradigms/ppo/`,
本 session 前刚 ship) 对齐。 同时为 `actor_main` 增加一个 paradigm-agnostic
的 lifecycle factory escape hatch,让 CFR 的 traversal-shaped lifecycle 与
DMC/PPO 的 episode-shaped lifecycle 同框运行而不污染 EpisodeRunner 的语义。

## 2. Architecture context

### 2.1 现状 — CFR 独立 mp 子系统

```
[parent: ParallelCFRTrainer.__init__]
  ├─ mp.get_context('spawn')
  ├─ in_qs = [mp.Queue() × N]                     ← 每 worker 1 个 in_q
  ├─ out_q = mp.Queue()                            ← 全部 worker 共用 1 个 out_q
  └─ procs = [spawn_worker(i, worker_cfg, in_q, out_q) × N]
       (worker.py:189 = mp.Process(target=cfr_worker_main, daemon=True))

[parent loop: _run_traversals(iteration)]
  ├─ weights_per_player = [net.cpu().state_dict().clone() × 2]   ← per iter
  ├─ for i in range(N): in_q[i].put(WorkItem(weights, n_trav, iter, seed_base, traverser_seq))
  ├─ for i in range(active_workers): result = out_q.get(timeout=remaining)   ← 同步 barrier
  └─ ingest_batches(...all_batches..., advantage_buffers, strategy_buffer, value_buffer, rng)

[child: cfr_worker_main(worker_id, cfg, in_q, out_q)]
  ├─ preload_dsl(cfg.data_dir)
  ├─ nets = [AdvantageNet(cfg.net_cfg).to(cpu) × 2]            ← spawn 后**持久**
  ├─ traverser = CFRTraverser(nets, ..., adv_cols, strat_col, val_col, traversal_cfg, rng)
  └─ while True:
       item = in_q.get()                                        ← 等 WorkItem
       if item is None: break
       for p in 0,1: nets[p].load_state_dict(item.weights_per_player[p])
       for k in range(item.n_traversals):
         env = _make_env(cfg, item.seed_base + k)
         traverser.traverse(env, item.traverser_seq[k], item.iteration)
         batches.append(drain_single_traversal(adv_cols, strat_col, val_col, traverser_p))
       out_q.put(WorkResult(worker_id, batches, wall_s))
```

观察:
- N+1 OS process (1 parent + N worker) — 比 DMC N+2 (含 InfServer) 少 1 个。
- Per-iter pickle:`weights_per_player` (2 个 state_dict, ~5-50 MB) 进
  每个 WorkItem → mp.Queue pickle 走 IPC pipe(parent 端 N+1 次 pickle,
  child 端 1 次 unpickle)。
- Per-traversal pickle:`batches` (List[CFRGameBatch],每 batch 含 obs
  tensors + sample dynamic dict) 出 out_q → parent pickle 1 次。
- Synchronous barrier:parent 必须 collect 全部 N worker 的 WorkResult
  才进 fit pass。 worker 间无 staggering。

### 2.2 目标 — DMC/PPO 模板对齐

```
[parent: CFRAsyncCollector.__init__]
  ├─ weights_shm = WeightsSHM(owner=True)
  ├─ weights_shm.write('cfr_adv_p0', net0.state_dict(), version=1)
  ├─ weights_shm.write('cfr_adv_p1', net1.state_dict(), version=1)
  ├─ network_blueprint_path = tempfile pickle.dump(2 net blueprint shapes)
  ├─ ipc_queue = IPCQueue(maxsize=...)
  ├─ runtime = Runtime(cfg, weights_shm=weights_shm)
  └─ runtime.start_actors(
       n_actors=cfg.pipeline.num_actors,
       actor_kwargs_factory=lambda i: dict(
         build_env_factory_path='training.paradigms.cfr.mp_factories.build_env_factory',
         build_opp_registry_path=...,
         build_policy_path=...,
         build_provider_path='training.paradigms.cfr.mp_factories.build_provider',
         spec_sampler_path='training.paradigms.cfr.mp_factories.cfr_spec_sampler',
         episode_runner_factory_path='training.paradigms.cfr.mp_factories.build_cfr_traversal_runner',  ← NEW (D1 选 B)
         transition_queue=ipc_queue,
         provider_kwargs={
           'weights_shm_info': weights_shm.serialize_for_worker(['cfr_adv_p0', 'cfr_adv_p1']),
           'network_blueprint_path': str(np_path),
         },
       ))

[child: actor_main spawn]
  ├─ harden_child_env(affinity=...)
  ├─ install_quiet_sigterm(stop_event)
  ├─ build_env_factory + build_opp_registry + build_policy + build_provider 走原 dispatch
  ├─ provider = build_provider(cfg, actor_id, **provider_kwargs)
  │   ↳ load 2 net blueprint, attach WeightsSHM, build CFRTraverser, hold internal state
  ├─ runner = resolve_builder(episode_runner_factory_path)(env_factory, opp_registry)
  │   ↳ For CFR: runner is CFRTraversalRunner (not EpisodeRunner)
  └─ while not should_stop():
       spec = spec_sampler(cfg, actor_id)             ← CFR spec encodes (iter, traverser_p, seed)
       output = runner.run(spec, policy, provider)    ← CFR runner runs 1 traversal
                                                        returns transition-shaped wrapper
       transition_queue.put(output)                    ← CFRGameBatch wrapped
       provider.update_weights()                       ← SHM poll 'cfr_adv_p0' + 'cfr_adv_p1'
```

### 2.3 关键 trade-off

Per CC-1: EpisodeRunner 不应被改造成 general "1 episode-or-traversal 运
行器" — `EpisodeRunner.run` 的 `our_player` 参数 + 单边 step + transition
list build 全是 episode 概念,traversal (双边递归 + tree walk + 双 player
都生 sample) 不 fit。 加 `episode_runner_factory` 是把 lifecycle runner
作为 paradigm-agnostic plugin,默认 EpisodeRunner,paradigm 可换。

## 3. D1: WorkItem-driven vs episode-driven lifecycle

**核心问题**:CFR worker 当前是 `while True: item = in_q.get()` (WorkItem
驱动,每 item 含 N traversal 批处理); `actor_main` 当前是 `while not
should_stop(): spec = spec_sampler(...); runner.run(spec, policy,
provider)` (episode 驱动,per-spec 1 run)。 如何调和?

### D1.A — Fake episode 包装 (spec.scenario_seed = workitem.seed_base + k)

```python
# mp_factories.py
def cfr_spec_sampler(cfg, actor_id) -> EpisodeSpec:
    seq = _CFR_COUNTERS.get(actor_id, 0)
    _CFR_COUNTERS[actor_id] = seq + 1
    iteration = seq // _TRAVERSALS_PER_ITER     # implicit
    traverser_p = seq % 2                        # alternate
    seed = _derive_seed(cfg.meta.seed, actor_id, seq)
    # 滥用 EpisodeSpec 字段携带 CFR 元数据:
    return EpisodeSpec(
        scenario_seed=seed,
        opponent_id=f'cfr_p{traverser_p}',       # ← 字段重用 (违反 EpisodeRunner 语义)
        epsilon=float(iteration),                 # ← 字段重用 (违反 EpisodePolicy 契约)
    )
```

然后让 `CFRTraversalPolicy.act` 内部识别 `opponent_id` 拆包,内部跑
`CFRTraverser.traverse`,返回一个 dummy action 让 EpisodeRunner step 一次
就结束。

**评估**:
- 优点:0 actor_main signature 改动,完全复用 EpisodeRunner。
- 缺点:
  - **架构污染** — EpisodeSpec 字段语义被 hijack,后续 reader 看代码不
    知道 `opponent_id='cfr_p0'` 是什么。
  - **EpisodePolicy.act 契约破** — `policy.act` 应返 `(action_idx,
    meta_dict)`,traversal 内部根本不产生 action_idx 序列 (递归走 tree),
    需要 fake 一个 (e.g. 0) 让 EpisodeRunner 不挂。
  - **EpisodeRunner.run 内部 transitions list 浪费** — traversal 已经
    push samples 到 CFR-local collector,EpisodeRunner 还会 build 一个
    `Transition` list 进 EpisodeRecord (fake reward + obs)。
  - 后续 reader 的语义 audit 失败概率高,违反 user 2026-05-22 决策
    `feedback_silent_decisions` (cfg/spec field 二义性是 silent
    behavioural)。
- **拒绝**。 fake episode 是 short-term hack,长期债务高,与 CFR change 的
  cleanup intent 反向。

### D1.B — actor_main 加 `episode_runner_factory: Callable | None` 字段(本 change 推荐)

```python
# core/actor/actor_process.py
def actor_main(
    actor_id, cfg, *,
    # ... existing builder/handoff kwargs ...
    episode_runner_factory: Callable[[Any, Any], Any] = None,
    episode_runner_factory_path: str = None,
) -> None:
    # ... existing dispatch ...
    if episode_runner_factory is None and episode_runner_factory_path is not None:
        episode_runner_factory = resolve_builder(episode_runner_factory_path)
    if episode_runner_factory is not None:
        runner = episode_runner_factory(env_factory, opp_registry)
    else:
        from training.core.actor.episode_runner import EpisodeRunner
        runner = EpisodeRunner(env_factory, opp_registry)
    # ... existing while loop (unchanged except for runner) ...
    while not should_stop():
        spec = spec_sampler(cfg, actor_id)
        output = runner.run(spec, policy, provider)
        item = output if push_episode_record else getattr(output, 'transitions', output)
        transition_queue.put(item)
        provider.update_weights()
```

CFR 端实现:

```python
# paradigms/cfr/mp_factories.py
class CFRTraversalRunner:
    def __init__(self, env_factory, opp_registry):
        self.env_factory = env_factory
        # opp_registry ignored (traversal 不需 opponent)
    def run(self, spec, policy, provider):
        # provider exposes traverser + collectors (CFR-specific)
        env = self.env_factory(spec.scenario_seed)
        try:
            stats = provider.traverser.traverse(
                env, traverser_player=spec.starting_player, iteration=spec.epsilon_as_iter()
            )
            batch = drain_single_traversal(
                provider.adv_cols, provider.strat_col, provider.val_col,
                traverser_player=spec.starting_player,
            )
        finally:
            env.close()
        # 返回 CFRGameBatch wrapper, episode_record-shape 但内容是 cfr_batches
        return _CFRRunnerOutput(transitions=[], cfr_batch=batch, ...)

def build_cfr_traversal_runner(env_factory, opp_registry):
    return CFRTraversalRunner(env_factory, opp_registry)
```

EpisodeSpec 字段约定 (CFR-local convention, design.md 记录):
- `scenario_seed: int` — 用法原义 (env seed)
- `starting_player: int (0/1)` — 重用承载 traverser_player(EpisodeRunner
  原义近似 — starting_player 就是从哪边开始;CFR 复用做 traverser_player)
- `opponent_id: str` — 固定 'cfr_traverser' (sentinel,不在 registry 查)
- `epsilon: float` — 重用承载 iteration int (cast back via `int(spec.epsilon)`)
- 其它字段保留默认

**评估**:
- 优点:
  - **actor_main 保持 paradigm-agnostic** — episode_runner_factory 是
    `Callable[[env_factory, opp_registry], Runner]`,Runner 唯一契约是
    `run(spec, policy, provider) → output`。 DMC/PPO 默认 EpisodeRunner,
    CFR 用 CFRTraversalRunner,future paradigm 任意 plug。
  - **EpisodeRunner 不被污染** — CFR-specific runner 是 paradigm-local
    file, episode_runner.py 保持当前 154 LOC 不动。
  - **复用 harden_child_env / install_quiet_sigterm / perf_trace / actor
    log 等 core/actor 资产** — 这些是 actor_main 内 ~140 LOC 的核心 child
    process setup,CFR-local cfr_actor_main 复写就是给 future 调试 actor
    init bug 时 (e.g. SIGTERM handler / CPU affinity) 双 path 都改的
    维护负担。
  - **provider_kwargs 复用 PPO 模板** — CFR 端 weights_shm_info + network
    blueprint path 完全沿 PPO change 已 ship 的 AB13 路径。
- 缺点:
  - actor_main signature 再扩一个字段 (从 PPO 加完后 21 字段 → 23 字段);
    需要 spec ADD AB14。
  - EpisodeSpec 字段 partial 重用 (epsilon as iter,starting_player as
    traverser_player) 是 paradigm-local convention,仍有 reader confusion
    风险 — mitigation: design.md + mp_factories.py docstring 显式 schema。
- **推荐**。 lifecycle 差异的根因是 episode-vs-traversal,把它打包成可换
  Runner factory 是最小且语义干净的对齐路径。 actor_main signature 扩张
  从 PPO change 的 provider_kwargs 算起还在可控范围 (paradigm-agnostic
  escape hatch 的 2 个对偶字段)。

### D1.C — Bypass actor_main,paradigm-local cfr_actor_main

```python
# paradigms/cfr/mp_factories.py
def cfr_actor_main(actor_id, cfg, *, weights_shm_info, ipc_queue, stop_event, ...):
    from training.core.actor._mp_helpers import harden_child_env, install_quiet_sigterm
    from training.core.perf import trace as _perf_trace
    affinity = ...  # 复制 actor_main 的 affinity 逻辑
    harden_child_env(affinity=affinity)
    install_quiet_sigterm(stop_event)
    _perf_trace.enable_from_cfg(cfg)
    # ... actor log setup 复制 ~ 20 LOC ...
    # CFR-specific:nets + traverser + adv_cols build + load weights
    nets = [AdvantageNet(...).to('cpu') for _ in range(2)]
    shm = WeightsSHM.attach(weights_shm_info)
    # ... load latest state_dict to nets ...
    traverser = CFRTraverser(nets, ..., adv_cols, strat_col, val_col, ...)
    while not stop_event.is_set():
        env = make_env(cfg, master_seed)
        traverser.traverse(env, traverser_player=..., iteration=...)
        batch = drain_single_traversal(...)
        ipc_queue.put(batch)
        # SHM poll latest
        for p in 0,1:
            sd, ver = shm.read(f'cfr_adv_p{p}')
            if sd is not None and ver > current_version[p]:
                nets[p].load_state_dict(sd)
        ...

# CFRAsyncCollector spawns via Runtime.start_actors with target=cfr_actor_main
```

**评估**:
- 优点:
  - lifecycle 完全 paradigm-local,actor_main 不动。
  - 字段重用问题不存在 (CFR 自定义 kwargs schema)。
- 缺点:
  - **复制 actor_main 中 ~ 140 LOC 的 child setup boilerplate** —
    harden_child_env + install_quiet_sigterm + perf trace enable +
    actor log dir + try/finally cleanup + queue cancel_join_thread。
    任何 actor init bug fix (e.g. recent SIGTERM handler 修补) 要同步
    两个 path,违反 DRY。
  - **失去 actor_main 的 builder dispatch 复用** — build_env_factory /
    build_provider 等 dotted-path resolve 也要 cfr-local 重新实现。
  - **失去 ActorProcess wrapper 复用** — ActorProcess.spawn /
    terminate 当前 hard-code target=actor_main (line 267);要么改
    ActorProcess.target 字段,要么 CFR 自建一个 mp.Process spawn wrapper。
  - lifecycle 差异从 1 个 plugin point (runner factory) 扩散到整个 actor
    setup,长期维护负担更高。
- 拒绝。 复用 core/actor 全套 child setup 是高价值,paradigm 不应再 fork
  child main。

### D1 决策:推荐 B

理由 summary:Runner factory 是 episode-vs-traversal 差异**唯一**接口,
把它打包成 paradigm-agnostic plugin 是最小切口;B 既保 actor_main 通用
性,又把 CFR-specific lifecycle 隔离在 paradigm-local Runner 实现;字段
重用 confusion 通过 docstring + spec 显式 schema 化压住。

## 4. D2: Weight transfer wire

**核心问题**:CFR 当前 per-WorkItem 带 2 个 state_dict pickle 走 mp.Queue
(`parallel_trainer.py:89`)。 DMC 走 InferenceServer + server 端 weights,
PPO 走 WeightsSHM + actor 端 poll。 CFR 应选哪个?

### D2.A — 全迁 WeightsSHM (本 change 推荐)

parent 在 `CFRAsyncCollector.__init__` 用 `WeightsSHM(owner=True)` write
2 个 slot (`'cfr_adv_p0'` / `'cfr_adv_p1'`); worker provider 在每
traversal 间隙 `update_weights` poll SHM,version 大于 current 时 load。

```python
# mp_factories.py build_provider
def build_provider(cfg, actor_id, *, weights_shm_info, network_blueprint_path):
    shm = WeightsSHM.attach(weights_shm_info)
    # network_blueprint_path: pickle.load → 2 个 AdvantageNet blueprint
    nets = pickle.load(open(network_blueprint_path, 'rb'))
    # initial load
    for p in 0,1:
        sd, ver = shm.read(f'cfr_adv_p{p}')
        if sd is None:
            raise RuntimeError(f'CFRAsync: WeightsSHM cfr_adv_p{p} cold')
        nets[p].load_state_dict(sd)
        nets[p].eval()
    traverser = CFRTraverser(nets, ..., adv_cols, strat_col, val_col, ...)
    return _CFRActorProvider(nets, traverser, shm, ...)

# _CFRActorProvider.update_weights
def update_weights(self):
    for p in 0,1:
        sd, ver = self._shm.read(f'cfr_adv_p{p}')
        if sd is not None and ver > self._current_version[p]:
            self._nets[p].load_state_dict(sd)
            self._current_version[p] = ver
```

**优点**:
- 与 PPO 100% 对齐 — `WeightsSHM.serialize_for_worker` + `attach` + read
  / write 路径已 ship + tested。
- 删除 per-WorkItem state_dict pickle (~ 5-50 MB × N worker × per iter)
  → SHM 写一次,N actor read 共享。
- weights_shm_info dict 复用 PPO 的 provider_kwargs 模板。
- CFR 频次低 (`traversals_per_iteration=64` 默认,每 iter 1 次 sync) ,
  SHM 写不是瓶颈 — 测试: 写一次 5 MB state_dict ≈ ms 级。

**缺点**:
- WeightsSHM API 要支持 N 个 named slot (CFR 用 2 个) — 已有
  `serialize_for_worker(slots: List[str])` 支持 multi-slot,no API change。
- iteration-staleness 容忍:actor 端 traversal 可能用 N-1 iter 的 weights
  跑 (与 trainer 端最新 net 略差),但这 OK (per memory
  `feedback_stale_weights_ok` — CFR/RL 异步对 stale weights 容忍)。

### D2.B — 保留 per-WorkItem state_dict 拷贝

parent 每 iter 把 `weights_per_player = [net.cpu().state_dict() × 2]`
pickle 进 WorkItem (mp.Queue 走),与现状一致。 但用 actor_main + mp_factories
模板:把 weights_per_player 当 `provider_kwargs` 字段 + 每 iter override
provider_kwargs (不可行,因 actor_main 当前 spawn 后 provider_kwargs 是
spawn-time 一次性 — actor 持续 loop 时无法再注入新 kwargs)。

实际可行实现:weights_per_player 走 `transition_queue` 反向 (control queue
+ data queue 分离),或单独加一个 control mp.Queue 让 parent 推 new
weights。

**评估**:
- 优点:与 CFR 原行为 1:1 等价 — iter boundary 清晰 (worker 收 weights
  → 做 N traversal → 返 batch → 再收 weights)。
- 缺点:
  - 引入额外 control wire (mp.Queue 2 条) — 与 DMC/PPO 不一致。
  - actor_main 不 native support reverse channel (需要把 provider 内部
    poll 一个 control_queue 实现 weight rotation,与 SHM poll 等价复杂度
    但接口非标准)。
  - per-iter pickle ~ 10-100 MB / N actor → 对 mp.Queue 吞吐有压力,
    虽然 CFR 频次低不算瓶颈,但与"统一架构"的 intent 反向。
- 拒绝。 与统一 wire 的 intent 直接冲突。

### D2.C — Hybrid: SHM 但 message 带 iteration

actor 通过 SHM read weights,但 parent 通过 mp.Queue 推一个轻量 control
message `{'iteration': N, 'reload_now': True}` 强 worker reload (而非
worker 自己 poll)。

**评估**:
- 优点:weight reload 时机由 trainer 严格控,无 stale weights。
- 缺点:
  - 引入 control queue 与 A 方案一致,失去简化收益。
  - 对 CFR 算法不必要 — `traverser.traverse(env, traverser_player,
    iteration)` 内部 iteration 是用来给 sample 打 tag 的,worker 端
    update_weights 时机不影响算法正确性 (advantage net 是函数,worker
    用 iter N 还是 N-1 的 net 拿 sample 都对)。
  - 加复杂度但 0 实际收益。
- 拒绝。

### D2 决策:推荐 A

理由:与 PPO 完全对齐,SHM API 已 ship,multi-slot natively supported,
CFR 频次低 SHM 写非瓶颈,stale weights 容忍 (memory backing);整体最简
路径。

## 5. D3: Synchronous barrier vs continuous loop

**核心问题**:`ParallelCFRTrainer._run_traversals(iteration)` 是同步 — 等
所有 worker 返 WorkResult 才 ingest_batches 推进 fit。 actor_main 是连续
loop — actor 一直产 episode,trainer 端 drain queue 决定何时停。 CFR async
collector 应哪种?

### D3.A — actor_main 加 barrier_event mp.Event

actor done 1 batch 后 `wait(barrier_event.set())`,trainer 端 set 推进下
一轮。

**评估**:
- 优点:保留 CFR 原 sync barrier 语义,iter weight version 严格对齐。
- 缺点:
  - 加 mp.Event 不是 actor_main 现有 signal — 需要再扩 signature。
  - barrier 是 paradigm-specific 同步原语,污染 paradigm-agnostic 模板。
  - 对 CFR 算法 / 正确性无价值 (D2 已论 stale weights OK)。
- 拒绝。 paradigm 不应往 actor_main 加同步原语。

### D3.B — Trainer per-iter 一次 spawn round (every iter spawn N actor →
join → ingest)

每 iter `runtime.start_actors(N)`,worker 跑 N/N traversal,push batch,
`should_stop()` set,worker exit; trainer ingest,然后下 iter 再 spawn N
个新 actor。

**评估**:
- 优点:严格保留 sync barrier 语义。
- 缺点:
  - **每 iter spawn cost (~ 100-500ms × N) × n_iterations (=100 默认)
    → 极昂贵** — process spawn 是慢操作,CFR 一 iter 本身 wall_s 可能
    才 1-10s,spawn cost 是 10-50% overhead。
  - 与连续 actor loop 模板分歧。
- 拒绝。 实际性能不可接受。

### D3.C — Actor 连续 loop + trainer drain queue (本 change 推荐)

actor 一直 sample + push CFRGameBatch 到 IPC queue; CFRAsyncCollector
.collect(n_units) drain `n_units` batch (e.g. 64) 返 CollectorOutput;
driver 推 fit_advantage,然后下一 collect。 weight version 通过 SHM 异
步广播,actor 自己 poll 时机不强约束。

```python
# CFRAsyncCollector.collect(n_units, provider)
def collect(self, n_units, provider):
    del provider  # CFRAsync owns its own SHM + provider in actor side
    self._iter_seq += 1
    target = int(n_units) if n_units > 0 else 64
    batches = []
    deadline = time.time() + self._drain_timeout_s
    while len(batches) < target and time.time() < deadline:
        try:
            item = self._queue.get(timeout=0.5)
        except Exception:
            continue
        if isinstance(item, _CFRRunnerOutput):
            batches.append(item.cfr_batch)
        # ...
    return CollectorOutput(
        transitions=[],
        runtime_metrics={'cfr_batches': batches, 'cfr_iteration': self._iter_seq},
        n_units=sum(b.n_samples() for b in batches),
    )
```

driver loop (paradigm.py step_schedule 已支持 — collect → buffer push →
train_n_batches → eval):

```
[driver]
  iter 0:  collect(64) → batches → buffer.push(via _CFRBufferBundle.push
                                              → ingest_batches)
           fit_advantage  → optimizer.step
  iter 1:  ...
  every N iter: sync_weights → SHM publish (actor 自动 pick up)
```

**评估**:
- 优点:
  - **与 DMC/PPO collect 契约 100% 对齐** — `Collector.collect(n_units,
    provider) → CollectorOutput`。
  - actor 自由产 batch,trainer 自由 drain — 利用率 high (无 barrier 闲置)。
  - sync_weights 通过 SHM 异步,与 PPO 一致。
- 缺点:
  - **失去 per-iter sharp weight boundary** — sample 可能 mix 不同 iter
    的 weights。 但这 OK (D2 论 stale weights;CFR 现行算法 invariant 仍
    成立 — advantage net 是 functional,sample 打 iteration tag 不依赖
    weights identity)。
  - traversal_seq 跨 iter 计数,与 trainer 端 iteration 解耦 — worker
    spec sampler 内自己维护 seq,与 trainer iter 不直接同步。 不影响
    CFR 数学 (per-sample iteration 进 advantage / strategy reservoir 是
    打 tag 用,不要求严格 monotonic)。
- **推荐**。 与 DMC/PPO 对齐,无 barrier 同步原语污染 actor_main。

### D3 决策:推荐 C

理由:对齐 Collector.collect / actor 连续 loop 模板 + 异步 SHM weight
broadcast,牺牲 sync barrier 但 stale weights 不影响 CFR 正确性 (memory
`feedback_stale_weights_ok` backing + CFR 算法 invariant analysis)。

## 6. D4: cfg shape

**核心问题**:CFR 现有 cfg 层次:`cfg.paradigm.cfr.*` (CFRParadigmConfig)
+ `cfg.paradigm.cfr.traversal` (CFRTraversalCfg) + `cfg.paradigm.cfr.agent`
(ObsShape)。 `cfg.pipeline.*` 是通用 (num_actors / mode / actor_backend)。
mp_factories 从哪读 + 是否引入新 cfg key?

### D4.A — 复用 cfg.pipeline.num_actors + mode='async' + actor_backend='python'

```toml
[pipeline]
mode = 'async'              # ← 触发 paradigm.make_collector 走 CFRAsyncCollector
num_actors = 4              # ← Runtime.start_actors(n_actors=4)
actor_backend = 'python'    # ← AB1-AB3 dispatch (CFR 不 support 'go',与 AZ/PPO 一致)

[paradigm]
version = '1.0.0'
paradigm = 'cfr'
# ... 现有 CFR 字段 ...
n_iterations = 100
traversals_per_iteration = 64

[paradigm.traversal]
sampling_mode = 'os'
epsilon = 0.1
# ...
```

CFR paradigm.make_collector 改:

```python
def make_collector(self, cfg, env_factory, network, opp_pool):
    mode = getattr(cfg.pipeline, 'mode', 'serial')
    if mode == 'serial':
        # ... 现状 CFRTraversalCollector ...
        return CFRTraversalCollector(cfg, pcfg, network, env_factory)
    if mode == 'async':
        from training.paradigms.cfr._async import CFRAsyncCollector
        return CFRAsyncCollector(cfg, pcfg, network, env_factory)
    raise ValueError(f"CFRParadigm.make_collector: cfg.pipeline.mode must be 'serial' or 'async', got {mode!r}")
```

mp_factories 读取契约:
- `cfg.pipeline.num_actors` — Runtime.start_actors 入参
- `cfg.scenario.team_0 / team_1 / card_pool / data_dir / max_rounds` —
  build_env_factory 走原 _make_env 路径
- `cfg.meta.seed` — _derive_seed master_seed
- `cfg.paradigm` (dict 形态) — 子进程拿 dict, build_provider 内
  `CFRParadigmConfig.from_dict(cfg.paradigm)` 反序列化 (与 DMC mp_factories
  line 156 模式一致)

**优点**:
- 与 PPO/DMC 完全对齐 — 0 新 cfg field,user cfg.toml 仅切换
  `mode='async' + num_actors=N` 即可启用 mp。
- AB3 status 表保持一致 — CFR 不 support `'go'` backend,raise on
  request (与 AZ/PPO 同 — 仅 DMC ship 了 Go subprocess path)。

**缺点**:无明显缺点。

### D4 决策:推荐 A

理由:简单且对齐 PPO/DMC,无新 cfg surface,user 切换 mp 仅需 2 个 pipeline
cfg field。

## 7. 关键 invariant 改动

### 7.1 spec.training-architecture/actor-backend.md (D1 选 B 路径)

新增 **AB14** (本 change ADD,**条件 D1 选 B**):

> `actor_main` 在 mp spawn 路径下 SHALL 通过可选 `episode_runner_factory:
> Callable[[env_factory, opp_registry], Runner] | None` 字段 (或对偶
> `episode_runner_factory_path: str | None` dotted-path) 接收 paradigm-
> specific lifecycle runner。 缺省值 None → 默认 `EpisodeRunner` (episode
> lifecycle,DMC/PPO/AZ/BC pattern)。
>
> Runner 契约 SHALL:
> - constructor `(env_factory, opp_registry) → Runner`
> - method `run(spec: EpisodeSpec, policy: EpisodePolicy, provider:
>   NetworkProvider) → output`
> - output SHALL be picklable; transition_queue.put 推送 output (或其
>   `.transitions` attr per `push_episode_record` flag)
>
> CFR (本 change) 提供 `CFRTraversalRunner` 走 traversal lifecycle (双边
> 递归 tree walk + sample push) 而非 episode lifecycle (单边步 + transition
> list);其 output 是 `_CFRRunnerOutput` (含 cfr_batch CFRGameBatch payload)。
>
> 不允许 runner 直接修改 actor_main 状态 (e.g. stop_event / transition_queue
> raw access); runner 通过 `output` 返回值传递数据。

AB1-AB13 不动。

### 7.2 spec.training-architecture/actor-backend.md (D1 选 C 路径)

无新 SHALL — 仅 AB1-AB13 适用。 design.md 记录 CFR-local cfr_actor_main
存在 (paradigm-local pattern,非 actor-backend invariant)。 风险:违反
spec audit "paradigm 不 fork child main" 隐含原则,需考虑加 negative
constraint AB(本设计选 B,不走此路径)。

## 8. Out-of-scope decisions

- **不动 DMC / PPO / AZ / BC**:本 change CFR-only。 AZ 留下一波
  (backlog #88 第三步 az-mp-pool-unification)。
- **不引 InferenceServer 到 CFR**:CFR 是 frozen tier,LocalNetworkProvider
  + WeightsSHM 简化模型对 advantage net forward 已足,与 PPO frozen tier
  一致。
- **不删 CFRTraversalCollector** (serial mode `collector.py:49`) —
  `mode='serial'` 仍走原路径,本 change 只新加 async path + 删
  parallel_trainer.py。
- **不动 CFR 算法 / traversal.py / advantage_net.py / strategy_net.py /
  fit_steps.py**。
- **不变 CFRGameBatch wire format** (transition_queue payload):仍 pickle
  `CFRGameBatch` 对象,与现有 `ingest_batches` 兼容。
- **不动 EpisodeRunner**:`episode_runner.py:25` 154 LOC 保留;CFR runner
  是 paradigm-local 新文件,不污染 core。
- **不删 ParallelCFRTrainer public API as compat shim**:grep 显示仅 2
  test file 用,无 production / configs 引用,直接删除,no migration shim。

## 9. Risk

1. **`episode_runner_factory` 设计扩 actor_main signature 第三次** (历
   史:inference_client → provider_kwargs → episode_runner_factory)。
   actor_main 字段数 21 → 23,docstring complexity 上升。 mitigation:
   docstring 用 calling convention table 列 3 类 paradigm pattern (DMC /
   PPO / CFR);每加一字段都对偶 paradigm-agnostic escape hatch (非 paradigm-
   specific 字段)。

2. **CFR 端 EpisodeSpec 字段 partial 重用 (epsilon as iter,starting_player
   as traverser_player) 是 paradigm-local convention,reader audit 失败
   风险**。 mitigation:
   - `cfr_spec_sampler` 内 docstring 显式 schema:
     `"""CFR EpisodeSpec encoding: scenario_seed=env seed,
     starting_player ∈ {0,1}=traverser_player, opponent_id='cfr_traverser'
     sentinel, epsilon=float(iteration)"""`
   - `CFRTraversalRunner.run` 内 schema decode 集中一处:
     `iteration = int(spec.epsilon); traverser_p = spec.starting_player`
   - 加 test `test_cfr_spec_encoding_roundtrip` 验编解码一致。

3. **CFRGameBatch pickle over IPC queue 吞吐**:CFR per-traversal batch
   size 中等 (~ 100-1000 sample × N float feature per sample),pickle 走
   mp.Queue 单次 ~ ms 级,N actor × 64 traversal/iter ≈ 256 batch/iter,
   queue drain 不应是瓶颈。 mitigation:e2e smoke_full 加 wall_s 阈值 (1
   iter ≤ 30s 在 Mac CPU-only,SLA),超时 fail。

4. **provider 内 N (=2) net + traverser + adv_cols + strat_col + val_col
   spawn-safe**:nets 通过 `pickle.load(network_blueprint_path)` 在 child
   端构造 (不 pickle pre-loaded torch module),adv_cols / strat_col /
   val_col 在 build_provider 内部 build (child-local 构造),全程不 pickle
   torch module 跨 spawn。 mitigation:e2e smoke_full 实测 spawn,pickle
   error trace 清晰。

5. **stale weights 实测影响 CFR 收敛 (per memory `feedback_stale_weights_ok`
   是 RL 通则,CFR 是否 OK 未严格验证)**:CFR advantage net 是 functional
   regressor (regret 估计),用 N-1 iter 的 net 估 regret 与 N iter 的 net
   估 regret 差异是 advantage net training 噪声同量级,不破坏 OS-MCCFR 收
   敛保证 (传统 CFR 也是 chunked update,iter 间不是 strict synchronization)。
   mitigation:smoke_full e2e 2-iter check (`advantage_loss` < N epoch
   threshold) 验证不 diverge。 frozen tier 不投入 production,严格收敛性
   研究不在本 change scope。

6. **`paradigm.py:make_collector` 是否 dispatch on `cfg.pipeline.mode`
   现状?** — 查 `paradigm.py:209`:`make_collector(cfg, env_factory,
   network, opp_pool)` 当前 hardcode 返 `CFRTraversalCollector`,no mode
   dispatch。 mitigation:本 change 改 make_collector 加 mode dispatch
   (与 PPOParadigm.make_collector 已有 dispatch 模式对齐;查 PPO 当前
   实现验)。

7. **删 `parallel_trainer.py` 是否破 import 链**:grep 显示无 production
   import,仅 tests/test_cfr_parallel_trainer.py + tests/test_cfr_worker.py
   import,两者一并删。

## 10. Flagged uncertainties (待 user 确认)

1. **D1.B EpisodeSpec 字段重用是否可接受?** 替代方案:扩 EpisodeSpec 加
   `traversal_iteration: int | None = None` + `traverser_player: int | None
   = None`,paradigm-agnostic 字段 (DMC/PPO 不用,CFR 用)。 这破坏 EpisodeSpec
   "scenario 描述" 语义但避免 field hijack。 待 user 决策 — 当前 design.md
   推荐 field 重用 + docstring 显式,但 spec 扩字段也合理。

2. **D3.C 中 driver 的 step_schedule(state, cfg) 与 async collect 协调**:
   现 `CFRParadigm.step_schedule` (`paradigm.py:238`) 是 iter-based —
   每 step 调 `collect(n_episodes=traversals_per_iteration)`,driver 在
   serial mode 跑 sync,async mode 时 collect 返 drained batch 是否够 N
   traversal?需要 deadline + retry。 现有 PPO async collect 已有此模
   式 (`_async.py:113` `drain_timeout_s=60.0`),CFR 沿用。 待
   implementation 时验 drain_timeout 默认值是否够 CFR 算法的 wall_s。

3. **`CFRAsyncCollector.sync_weights(network)` 签名**:network 是
   `CFRNetwork` 包 advantage_head(0) + advantage_head(1) + strategy_net,
   本 change 只 sync 2 个 advantage_head (worker 不需 strategy_net,
   strategy_net 是 trainer 端 fit_strategy 用)。 待确认 — 当前 design
   假定 sync 只覆 advantage 2 个 head,strategy_net trainer-local。 与
   CFR 算法语义一致 (worker 只跑 advantage forward / regret matching)。

## 11. Acceptance gate

- `pytest -n 4 training/paradigms/cfr/tests/ training/core/actor/tests/ -q`
  全 PASS (no regress)。
- 新加 `test_cfr_mp_factories.py` PASS (build_provider 构造 / Runner.run
  调用契约 / spec encode-decode roundtrip)。
- 新加 `test_cfr_async_mp_e2e.py` smoke_full PASS (2 actor + 1 iter 8
  traversal + sync_weights + clean shutdown,wall ≤ 30s Mac)。
- `pytest -m smoke training/tests/ -q -k cfr` 全 PASS (CFR serial smoke
  不 break)。
- `pytest -m smoke_full training/tests/test_cfr_smoke_full.py -v` PASS
  (per memory `feedback_symmetric_tests` — CFR smoke_full driver e2e 不
  break,因 step_schedule 与 mp_factories 独立)。
- ruff format clean + line limit hooks 全 pass (mp_factories.py < 300
  LOC,_async.py < 300 LOC,actor_process.py 加 episode_runner_factory
  后仍 < 300 LOC)。
- `parallel_trainer.py` + `worker.py` 完全删除 (-373 LOC),`test_cfr_
  parallel_trainer.py` + `test_cfr_worker.py` 完全删除 (-348 LOC)。
