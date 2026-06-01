---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: ppo-mp-pool-unification
---

# Design — PPO mp pool unification + actor_main provider_kwargs 通用字段

## 1. Goal

把 PPO `_async.py` 的 env-var-based spawn handoff (3 个 env var +
tempfile pickle) 砍掉, 切换到 DMC 模板的 `actor_kwargs_factory` 注入模式;
为 actor_main 增加 paradigm-agnostic `provider_kwargs` 通用字段, 让 future
paradigm 加 mp 时不再需要扩 actor_main signature。

## 2. Architecture context

### 2.1 现状 — PPO 用 env var spawn handoff (W3a 时代遗留)

```
[parent: PPOAsyncCollector.__init__]
  ├─ WeightsSHM.serialize_for_worker(['latest']) → pickled bytes
  ├─ network.cpu() → pickled bytes
  ├─ os.environ[_ENV_SHM_PATH] = tempfile path
  ├─ os.environ[_ENV_NET_PATH] = tempfile path
  ├─ os.environ[_ENV_OPPONENT] = paradigm_cfg.rollout.rollout_opponent
  └─ Runtime.start_actors(
       actor_kwargs_factory=lambda i: dict(
         build_env_factory_path='training.paradigms.ppo._async.build_env_factory',
         build_opp_registry_path=..., build_policy_path=...,
         build_provider_path='training.paradigms.ppo._async.build_provider',
         spec_sampler_path=..., transition_queue=ipc_queue))

[child: actor_main spawn]
  ├─ resolve_builder('training.paradigms.ppo._async.build_provider')
  └─ build_provider(cfg, actor_id):
       ├─ shm_path = os.environ[_ENV_SHM_PATH]  ← 跨进程隐式状态
       ├─ net_path = os.environ[_ENV_NET_PATH]
       └─ ... pickle load + SHM attach + LocalNetworkProvider 包装
```

问题:env var 是全局 process-wide state, parent set 后影响整个 process 内
所有 spawn (虽然 PPOAsyncCollector close 内有 pop, 但 test 必须配对 setup/
teardown, 单测可见性差)。 spec_sampler 也通过 env var 读 opp_id, 与
build_opp_registry 走两条 path 拿同 cfg。

### 2.2 目标 — DMC 模板对齐

```
[parent: DMCMultiProcessCollector._bootstrap]
  ├─ runtime.publish_weights(sd_cpu, version=0)
  ├─ inference_clients = [InferenceClient.attach_to_server(server) × N]
  └─ runtime.start_actors(
       actor_kwargs_factory=lambda i: dict(
         build_env_factory_path='training.paradigms.dmc.mp_factories.build_dmc_env_factory',
         build_provider_path='training.paradigms.dmc.mp_factories.build_dmc_provider',
         inference_client=clients[i],  ← parent-constructed spawn-safe object
         transition_queue=self.ring, push_episode_record=True))

[child: actor_main spawn]
  ├─ resolve_builder('...build_dmc_provider')
  └─ if inference_client is not None:
       provider = build_provider(cfg, actor_id, inference_client=inference_client)
```

DMC pattern 关键:parent 构造好 spawn-safe object → 通过
`actor_kwargs_factory` 注入 mp.Process kwargs → child actor_main dispatch 到
build_provider 时把这些 object 作为 kwargs 透传。 **零 env var, 零 tempfile
on cfg path** (network blueprint tempfile 仍存在, 但 cfg 字段都走 mp pickle
auto-share)。

### 2.3 目标 — PPO 切换后

```
[parent: PPOAsyncCollector.__init__]
  ├─ WeightsSHM.serialize_for_worker(['latest']) → spawn-safe dict
  │   (内部 _SHMSlot.__getstate__ 把 SharedMemory 名字 + Lock pickle 化,
  │    child 端 WeightsSHM.attach(info) 重新 mmap, 不依赖 tempfile)
  ├─ network.cpu() → pickle.dump(... tempfile)  ← network blueprint 仍 tempfile
  │                                                (frozen tier 不引入 InfServer)
  └─ Runtime.start_actors(
       actor_kwargs_factory=lambda i: dict(
         build_env_factory_path='training.paradigms.ppo.mp_factories.build_env_factory',
         build_provider_path='training.paradigms.ppo.mp_factories.build_provider',
         spec_sampler_path='training.paradigms.ppo.mp_factories.spec_sampler',
         transition_queue=ipc_queue,
         provider_kwargs={
           'weights_shm_info': weights_shm_info,         ← spawn-safe dict
           'network_blueprint_path': str(np_path)}))     ← tempfile path str

[child: actor_main spawn]
  ├─ resolve_builder('training.paradigms.ppo.mp_factories.build_provider')
  └─ if provider_kwargs:
       provider = build_provider(cfg, actor_id, **provider_kwargs)
       # → WeightsSHM.attach(weights_shm_info) + pickle.load(network_blueprint_path)
```

`opp_id` 读法:`build_opp_registry(cfg)` + `spec_sampler(cfg, actor_id)` 都
读 `cfg.paradigm['rollout']['rollout_opponent']`, 与 cfg 流通对齐 (mp spawn
auto-pickle cfg 整体, child 进程直接拿到 dict 形态的 cfg.paradigm)。

## 3. `actor_main` provider_kwargs 设计

### 3.1 字段定义

```python
def actor_main(
    actor_id: int,
    cfg: Any,
    *,
    # existing builder kwargs (unchanged)
    build_env_factory: Callable = None,
    build_opp_registry: Callable = None,
    build_policy: Callable = None,
    build_provider: Callable = None,
    spec_sampler: Callable = None,
    transition_queue: Any = None,
    should_stop: Optional[Callable[[], bool]] = None,
    # dotted-path versions (unchanged)
    build_env_factory_path: Optional[str] = None,
    build_opp_registry_path: Optional[str] = None,
    build_policy_path: Optional[str] = None,
    build_provider_path: Optional[str] = None,
    spec_sampler_path: Optional[str] = None,
    # existing parent-handoff kwarg (DMC pattern, unchanged)
    inference_client: Any = None,
    # NEW (this change) — generic kwargs handoff (PPO pattern):
    provider_kwargs: Optional[dict] = None,
    stop_event: Any = None,
    push_episode_record: bool = False,
) -> None:
```

### 3.2 Dispatch matrix (build_provider call)

```python
if inference_client is not None and provider_kwargs is not None:
    raise ValueError(
        f'actor_main[actor_id={actor_id}]: inference_client + provider_kwargs '
        'mutually exclusive — pass one or neither.'
    )
if inference_client is not None:
    provider = build_provider(cfg, actor_id, inference_client=inference_client)
elif provider_kwargs:
    provider = build_provider(cfg, actor_id, **provider_kwargs)
else:
    provider = build_provider(cfg, actor_id)
```

**互斥 rationale**:
- `inference_client` 是 single-object handoff pattern (DMC: parent-constructed
  InferenceClient, 直接当 build_provider 的 named kwarg)。
- `provider_kwargs` 是 generic-dict handoff pattern (PPO: 多个 spawn-safe
  param 集 dict, build_provider 展开 `**kwargs`)。
- 两者都用 → 二义性:DMC paradigm 应该把 client 放 provider_kwargs 还是
  inference_client?互斥 raise 早 fail。
- neither → 退到 legacy 两参数 `(cfg, actor_id)` build_provider 签名 (AZ
  当前不需要 parent-side handoff, 现状保留)。

### 3.3 spawn-safe 约束

`provider_kwargs` 字典内的所有 value SHALL picklable by `mp.Process`
spawn ctx (pickle protocol 4+):

- **OK**:dict / list / tuple / str / int / float / bytes / Path str /
  `_SHMSlot` 实例 (内部 `__getstate__` 已实现) / `WeightsSHM.serialize_for_worker`
  返 dict / `mp.Queue` / `mp.Event` / `mp.Lock`。
- **NOT OK**:`torch.nn.Module` 实例 / open file handles / sockets /
  un-pickleable thread state / cgo handles。

Parent 端 caller 不正确传值 → mp.Process spawn 抛 `pickle.PicklingError` 或
`TypeError`, 在 caller stack 暴露 (test 必验)。 actor_main 不主动 validate
(下沉到 build_provider 实现, paradigm 自行 schema check)。

## 4. PPO handoff bundle 设计

### 4.1 候选方案

**A. dict provider_kwargs (本 change 选)**:
```python
provider_kwargs = {
    'weights_shm_info': self._weights_shm.serialize_for_worker(['latest']),
    'network_blueprint_path': str(np_path),
}
build_provider(cfg, actor_id, *, weights_shm_info, network_blueprint_path)
```

**B. `_PPOWeightsHandoff` dataclass**:
```python
@dataclass
class _PPOWeightsHandoff:
    weights_shm_info: dict
    network_blueprint_path: str

provider_kwargs = {'handoff': _PPOWeightsHandoff(...)}
build_provider(cfg, actor_id, *, handoff: _PPOWeightsHandoff)
```

**C. 直接当 actor_kwargs 平铺**:
```python
actor_kwargs_factory=lambda i: dict(
    weights_shm_info=..., network_blueprint_path=..., ...)
```

### 4.2 选择 A 的理由

- **B 过度封装**:PPO frozen tier 不预期再加新字段, dataclass 是无回报开销;
  字段 dict 已是结构清晰的 wire schema。
- **C 破坏 actor_main 接口纯洁性**:`actor_kwargs` 直接 = mp.Process kwargs,
  把 paradigm-specific 字段 (weights_shm_info) 塞进去 = actor_main 必须知道
  PPO 字段名, 失去 paradigm-agnostic 约束。 provider_kwargs 是显式 escape
  hatch — actor_main 不感知里面具体什么, 透传到 build_provider 由 paradigm
  解析。
- **A 与 DMC inference_client 对偶**:DMC = single object handoff,
  PPO = dict bundle handoff;两个 escape hatch 互斥, future paradigm 任挑
  一个 fit, 不需要再扩 actor_main signature。

## 5. 关键 invariant 改动

### 5.1 spec.training-architecture/actor-backend.md

新增 **AB13** (本 change ADD):

> `actor_main` 在 mp spawn 路径下 SHALL 通过两个互斥 escape hatch 之一接收
> parent-constructed spawn-safe object:
> - `inference_client: Any`:single-object handoff (DMC pattern,
>   InferenceClient handle)
> - `provider_kwargs: dict | None`:generic-kwargs bundle handoff (PPO
>   pattern,SHM info + tempfile path str)
>
> 两者都 None → build_provider 走 legacy `(cfg, actor_id)` 签名 (AZ pattern)。
> 两者都给 → SHALL raise ValueError。 `provider_kwargs` dict 内值 SHALL
> picklable by `mp.Process` spawn ctx。 actor_main 不 validate 内部 schema
> (下沉到 build_provider 实现)。

AB1-AB12 保持不变 (与 actor_backend / Go subprocess / N+2 topology 等无关)。

## 6. Out-of-scope decisions

- **不扩 spec 到 AZ/CFR/BC** — AB13 文字 describes 当前 PPO + DMC 接通的事实,
  future AZ port 时 reuse 已有 dispatch 不需要新 SHALL。
- **不引 InferenceServer 到 PPO**:PPO frozen tier 不投入 production,
  LocalNetworkProvider + WeightsSHM 是简化的 spawn-safe 模型, 改 InfServer
  增量太大无收益 (与 ADR-0008 frozen 决策对齐)。
- **不删 `Runtime.start_actors` 旧 `actor_kwargs` shared dict 模式**:本
  change 不破坏 actor_kwargs 静态共享 path (test 还在用); 只是 PPO 切换到
  actor_kwargs_factory 注入 provider_kwargs。

## 7. Risk

1. **`provider_kwargs` dict 内 spawn-unsafe object 漏过 review**:
   mitigation:加 e2e smoke_full test 实测 spawn — 不 spawn-safe 在 e2e
   时 hard fail (PicklingError trace 清晰); unit test 用 mock provider_kwargs
   验 dispatch 正确, 不验 pickle (mock 内值 trivially picklable)。

2. **`cfg.paradigm['rollout']['rollout_opponent']` 子进程读取失败**:
   mp spawn ctx 自动 pickle 整 cfg, dict 内嵌 dict 是 trivially picklable;
   mitigation:e2e smoke_full 跑真 spawn 验 child 端读到的 opp 与 parent
   一致 (与 spec_sampler 已 test 的逻辑无 regress)。

3. **`mp_factories.py` 内 import 链路 cycle (paradigm.py → collector.py →
   _async.py → mp_factories.py?)**: 不 cycle — `_async.py` 通过 dotted
   string 引用 mp_factories.build_*, parent 端不直接 import build_*
   functions; dispatch 通过 `resolve_builder` 在 child 端 lazy import,
   parent 端 mp_factories module 完全不 load。 mitigation:test 验
   `from training.paradigms.ppo._async import PPOAsyncCollector` 不触发
   `mp_factories` import。

## 8. Acceptance gate

- `pytest -n 4 training/tests/test_ppo_async.py training/core/actor/tests/ -q`
  全 PASS (no regress on existing test)。
- 新加 `test_ppo_async_provider_kwargs_handoff` PASS (covers AB13 dispatch
  matrix)。
- `pytest -m smoke training/tests/ -q -k ppo` 全 PASS (PPO smoke 不 break)。
- `pytest -m smoke_full training/tests/test_ppo_async_mp_e2e.py -v` 可
  opt-in 跑 (本 change verify 不要求 default 跑,但 file 必须 syntactically
  callable + reach 1 episode in dispatch)。
- ruff format clean + line limit hooks 全 pass (`_async.py` < 300 LOC,
  `mp_factories.py` < 300 LOC, `test_ppo_async.py` < 500 LOC)。
