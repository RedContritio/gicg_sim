---
change_id: cfr-mp-pool-unification
capability: training-architecture
delta_type: ADD
target_subtopic: actor-backend
---

# Spec Delta — training-architecture / actor-backend

> 本 delta 加 1 SHALL (AB14) 到 `openspec/specs/training-architecture/actor-backend.md`
> § 3 SHALL invariants 末尾 (merge target anchor:§ 3.6 末 AB13 之后)。
>
> AB1-AB13 不动 (`actor_backend` dispatch / N+2 OS process topology / 0 cgo /
> TCP-only inference wire / atomic spawn-shutdown / AB13 provider-handoff escape
> hatches 全保留)。 AB14 是 AB13 之外**正交**的第二个 escape-hatch 轴。

## [ADD] § 3.7 actor_main lifecycle-runner factory escape hatch

**AB14**: `training.core.actor.actor_process.actor_main` SHALL 接受一个可选的
paradigm-agnostic lifecycle-runner factory,让不同 paradigm 注入与自身 episode
/ traversal lifecycle 匹配的 runner,而不污染 `EpisodeRunner` 的 episode 语义:

- **`episode_runner_factory: Callable[[env_factory, opp_registry], Runner] | None`**
  — single-callable handoff (in-proc 路径)。 actor_main SHALL 调用
  `episode_runner_factory(env_factory, opp_registry)` 得到 runner。
- **`episode_runner_factory_path: str | None`** — dotted-path 对偶 (cross-process
  spawn 路径)。 actor_main SHALL 用 `resolve_builder(episode_runner_factory_path)`
  resolve 出 callable,语义与上等价。
- **缺省 (两者皆 None)** → actor_main SHALL 构造默认 `EpisodeRunner(env_factory,
  opp_registry)` (episode lifecycle,DMC/PPO/AZ/BC pattern,行为与 AB14 引入前
  完全一致)。

**Runner 契约** SHALL:

- constructor `(env_factory, opp_registry) → Runner`。
- method `run(spec: EpisodeSpec, policy: EpisodePolicy, provider: NetworkProvider)
  → output`。
- `output` SHALL picklable;actor_main SHALL 把它推到 `transition_queue` (或其
  `.transitions` attr,per `push_episode_record` flag — 与 default EpisodeRunner
  output 走同一 push 路径)。
- runner SHALL NOT 直接触碰 actor_main 内部状态 (`stop_event` /
  `transition_queue` raw access);runner 只通过 `run` 返回值传递数据。 stop
  信号 / queue push 由 actor_main loop 拥有。

**正交约束** (NOT mutual exclusion):`episode_runner_factory` 与 AB13 的
`inference_client` / `provider_kwargs` 是**独立的两条轴**,SHALL NOT 进 AB13 的
互斥 ValueError 检查。 三个 escape hatch 自由组合:

- DMC 设 `inference_client`,无 runner factory (default EpisodeRunner)。
- PPO 设 `provider_kwargs`,无 runner factory (default EpisodeRunner)。
- CFR (本 change) **同时**设 `provider_kwargs` (WeightsSHM handoff) **AND**
  `episode_runner_factory` (`CFRTraversalRunner`) — 两者 compose,无冲突。

CFR 提供的 `CFRTraversalRunner` 走 traversal lifecycle (双边递归 tree walk +
双 player 都生 sample) 而非 episode lifecycle (单边步 + transition list);其
output 是 `_CFRRunnerOutput` (含 cfr_batch `CFRGameBatch` payload)。

**Rationale**:
- CFR 的 traversal lifecycle 与 DMC/PPO/AZ 的 episode lifecycle 根本不同
  (`EpisodeRunner.run` 的 `our_player` 单边 step + transition list build 全是
  episode 概念,traversal 不 fit)。 把 lifecycle runner 抽成 paradigm-agnostic
  plugin 是 episode-vs-traversal 差异的**唯一**接口,最小切口。
- 选 plugin (D1=B) 而非 fork CFR-local `cfr_actor_main` (D1=C):后者要复制
  actor_main 内 ~140 LOC child setup (env hardening / SIGTERM handler / perf
  trace / per-actor logging / queue cleanup),任何 actor init bug fix 都要双 path
  同步,违反 DRY。 plugin 让 CFR 复用全套 core child setup,只换 lifecycle runner。
- 正交而非互斥:provider-handoff 轴 (AB13:parent → child 资源传递) 与
  lifecycle-runner 轴 (AB14:episode-vs-traversal 运行形态) 是不同维度,CFR
  恰好两轴都用。 把 AB14 塞进 AB13 互斥检查会错误地排除合法组合。
- `EpisodeRunner` 不被改造成 general "episode-or-traversal 运行器" (CC-1):
  CFR runner 是 paradigm-local file,`episode_runner.py` 154 LOC 不动。

**Failure mode if violated**:
- runner output 非 picklable → `transition_queue.put` (mp.Queue / IPCQueue) 抛
  `pickle.PicklingError`,在 actor child stack 暴露 — actor_main 不主动检测
  (下沉到 paradigm runner 约束)。
- runner 直接读写 `stop_event` / `transition_queue` → 绕过 actor_main loop 的
  push / stop 编排,破坏 lifecycle 单一所有权,引入难定位的 shutdown / 重复 push
  bug;故契约禁止。
- 若错误地把 `episode_runner_factory` 加进 AB13 互斥检查 → CFR 合法的
  `provider_kwargs` + `episode_runner_factory` 组合被早 fail,阻断 CFR mp 路径。

**Code references** (post-implement):
- `training/core/actor/actor_process.py:actor_main` — `episode_runner_factory` +
  `episode_runner_factory_path` 字段 + dotted-path resolve + runner dispatch
  (None → `EpisodeRunner`),**不**进 AB13 互斥 raise。
- `training/core/actor/episode_runner.py:EpisodeRunner` — 默认 episode-lifecycle
  runner (DMC/PPO/AZ/BC),AB14 引入后不动。
- `training/paradigms/cfr/mp_factories.py:build_cfr_traversal_runner` +
  `CFRTraversalRunner` — AB14 escape hatch 的 CFR 实现 (traversal lifecycle,
  later task)。
- `training/core/actor/tests/test_actor_main_runner_factory.py` — AB14 dispatch
  契约 (factory used over default / path resolved / 与 provider_kwargs 正交不
  raise / AB13 互斥不受 AB14 影响)。
