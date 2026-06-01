---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: ppo-mp-pool-unification
---

# Proposal — PPO mp actor pool 统一到 DMC 模板 (env var hack 砍)

## 1. Why

I31 backlog #88 (AZ/CFR/PPO mp actor pool 统一到 core/actor.actor_main) audit
显示 PPO `_async.py` 已经走 `Runtime.start_actors + actor_main` dotted-path
入口 — 但 spawn handoff 仍走 W3a (FU-W3b-PPO) 时代遗留的 **env var
(`_ENV_SHM_PATH` / `_ENV_NET_PATH` / `_ENV_OPPONENT`) + tempfile pickle**
历史 hack。 三层痛点:

1. **隐式 cross-process 通讯**:env var 是全局 state,parent / child 的耦合
   不可见;test 必须 set/clear env 才能验 build_provider /spec_sampler 行为。
   与 user 2026-05-23 决策 `feedback_cfg_driven_only` 反 (runtime 行为应由
   cfg 决定,不走 env var)。

2. **DMC 模板已立**:DMCMultiProcessCollector `_bootstrap` (`collector.py:205`)
   通过 `actor_kwargs_factory=lambda i: dict(base, inference_client=clients[i])`
   把 spawn-safe object (InferenceClient) 注入 mp.Process kwargs — 这是
   golden template, AZ/CFR mp 后续也应对齐。 PPO 当前用 env var bypass
   这个机制是历史包袱,不是 architectural intent。

3. **`actor_main` 字段已扩展过 inference_client**: 现签名已支持
   paradigm-agnostic 透传字段 (line 80 `inference_client`),只需再加一个
   通用 `provider_kwargs: dict | None` 就能让 PPO 干净对齐 — 不需要为
   PPO 加专用字段,不需要每加 paradigm 改 actor_main。

cleanup risk low:
- PPOAsyncCollector 当前是 frozen tier (per ADR-0008 + `paradigm.py:16`),
  production 不投入 — pure refactor,无 perf 影响。
- mock-only `test_ppo_async.py` 244 LOC 全 pass,改 import + 删 env var
  setup 即可 (~ 30 LOC 改动)。
- DMC / AZ / CFR / BC 不动 — PPO-local change。

## 2. What

**4 part cleanup** (LOC budget ~ -50 net):

1. **扩 `actor_main` 加 `provider_kwargs: dict | None` 字段**
   (`training/core/actor/actor_process.py`):paradigm-agnostic 透传 kwargs
   到 `build_provider(cfg, actor_id, **provider_kwargs)`。 与现有
   `inference_client` 字段互斥 (两者都给 raise ValueError),spawn-safe
   要求 dict 内值必须 picklable。 更新 docstring 写 3 calling convention:
   `inference_client` (DMC pattern) / `provider_kwargs` (PPO pattern) /
   neither (legacy AZ pattern,build_provider 不需 parent-side handoff)。

2. **新建 `training/paradigms/ppo/mp_factories.py`** (~ 160 LOC):
   从 `_async.py` 搬 5 件套 + provider class — `build_env_factory` /
   `build_opp_registry` / `build_policy` / `build_provider` / `spec_sampler`
   + `_PPOActorProvider`。 模块开头 docstring 写 DMC 模板对齐说明。
   - `build_opp_registry` / `spec_sampler`:**删 `os.environ.get(_ENV_OPPONENT, ...)`**
     改读 `cfg.paradigm['rollout']['rollout_opponent']` (cfg 通过 mp spawn
     auto-pickle 流转,子进程拿到完整 cfg)。
   - `build_provider`:签名改 `(cfg, actor_id, *, weights_shm_info,
     network_blueprint_path)` — 显式 kwargs 替代 env var,kwargs 由 parent
     通过 `actor_kwargs_factory` 注入 `provider_kwargs`。

3. **缩 `training/paradigms/ppo/_async.py`** (~ 130 LOC):
   - 删 `_ENV_SHM_PATH` / `_ENV_NET_PATH` / `_ENV_OPPONENT` 三常量。
   - 删 `os.environ[...] = ...` 设置 + close 内 `os.environ.pop` 循环。
   - 删 build_* / spec_sampler / `_PPOActorProvider` (已搬到 mp_factories)。
   - `__init__` 内直接构造 `weights_shm_info = self._weights_shm.serialize_for_worker(['latest'])`
     + `network_blueprint_path = str(np_path)` (network pickle 仍 tempfile,
     这是 picklable network blueprint 的标准 spawn-safe handoff,不在本
     change scope cleanup)。
   - `start_actors` 改 `actor_kwargs_factory=lambda i: dict(kw,
     provider_kwargs={'weights_shm_info': ..., 'network_blueprint_path': ...})`
     — dotted-path 改指 `training.paradigms.ppo.mp_factories.build_*`。

4. **改 `training/tests/test_ppo_async.py`**:
   - 改 4 个 test 的 import 路径 (build_policy / spec_sampler /
     `_PPOActorProvider` 已搬到 mp_factories)。
   - `test_ppo_async_spec_sampler_monotonic_and_self_to_random`:删 env var
     setup,用 cfg stub set `cfg.paradigm['rollout']['rollout_opponent']`
     测试。
   - 新加 `test_ppo_async_provider_kwargs_handoff`:测 actor_main 走
     `provider_kwargs` path → `build_provider(cfg, actor_id, **kwargs)`
     (mock build_provider 验证 kwargs 透传)。
   - 新加 `test_ppo_async_mp_e2e.py` (smoke_full marker):2-actor 真 spawn
     + 1-2 episode + weight sync + clean shutdown。

## 3. Affected specs

- `openspec/specs/training-architecture/actor-backend.md` ADD AB13:
  paradigm-agnostic `provider_kwargs: dict | None = None` 字段约束
  (互斥 + spawn-safe + dispatch matrix)。 保留 AB1-AB12 不动。

## 4. Out of scope

- **不动** DMC / AZ / CFR / BC — 4 paradigm 不在本 change scope (DMC golden
  已 ship, AZ/CFR/BC `_bootstrap` 单独 audit ticket 决定是否对齐 — backlog
  #88 主要目标 PPO env var hack 砍, 已成立)
- **不删** PPO `network blueprint tempfile pickle` 路径:这是 picklable
  network spawn-safe handoff 的标准模式 (DMC InferenceServer-mediated 路径
  不适用 PPO frozen tier 的 LocalNetworkProvider 设计), 保留
- **不改** PPOAsyncCollector 行为 (collect / sync_weights / state_dict /
  load_state_dict 全保留, pure refactor)
- **不投入 production**:PPO 仍 frozen tier (ADR-0008 + `paradigm.py:16`),
  cleanup 不解 frozen
- **不新增 cfg 字段**:weights_shm_info / network_blueprint_path 通过
  `provider_kwargs` 运行时传, 不进 cfg.toml
- **不改其他 actor_main 字段**:`inference_client` / `transition_queue` /
  `stop_event` / `should_stop` / `push_episode_record` 全保留

## 5. Decision summary

- **[CC-1] `provider_kwargs` 字段而非 `_PPOWeightsHandoff` dataclass**:
  paradigm-agnostic 通用字段 > paradigm-specific dataclass; future paradigm
  加 mp 时 reuse 无需扩 actor_main signature 再次。
- **[CC-2] 与 `inference_client` 互斥 (两者都给 raise)**:语义清晰 —
  inference_client 是 client-handoff pattern (DMC), provider_kwargs 是
  generic-kwargs pattern (PPO); 互斥避免 build_provider 二义性。
- **[CC-3] `opp_id` 走 cfg, 不走 env**:与 `feedback_cfg_driven_only`
  对齐, runtime 行为由 cfg 决定; 子进程通过 mp pickle 自动拿到完整 cfg
  无需额外 wire。
- **[CC-4] mp_factories.py 不 import _async (回避 cycle)**:`_async.py`
  内部用 dotted-path string 引用 `mp_factories.build_*`, parent 端不直接
  import build_*; dispatch 通过 `resolve_builder` 在 child 端 lazy resolve,
  无 import cycle。
- **Effort**:~250 LOC net (-50 actor_main env-var-free + -100 _async cleanup
  + +200 mp_factories + +30 test 改 + +70 e2e test) + 4 OpenSpec artifact ~ 300 LOC。
