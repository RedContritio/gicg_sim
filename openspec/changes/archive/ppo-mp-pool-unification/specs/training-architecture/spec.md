---
change_id: ppo-mp-pool-unification
capability: training-architecture
delta_type: ADD
target_subtopic: actor-backend
---

# Spec Delta — training-architecture / actor-backend

> 本 delta 加 1 SHALL (AB13) 到 `openspec/specs/training-architecture/actor-backend.md`
> § 3 SHALL invariants 末尾 (merge target anchor:§ 3.5 末 AB12 之后)。
>
> AB1-AB12 不动 (`actor_backend` dispatch / N+2 OS process topology / 0 cgo /
> TCP-only inference wire / atomic spawn-shutdown 全保留)。

## [ADD] § 3.6 actor_main parent-handoff escape hatches

**AB13**: `training.core.actor.actor_process.actor_main` 在 mp spawn 路径下 SHALL
通过两个互斥 escape hatch 之一接收 parent-constructed spawn-safe object,
让 paradigm build_provider 拿到 mp.Queue / SHM info / pickled handle 等 child
端无法 reconstruct 的资源:

- **`inference_client: Any`** — single-object handoff (DMC pattern,
  parent-constructed `InferenceClient` handle attached to shared
  `InferenceServer`)。 actor_main SHALL 调用
  `build_provider(cfg, actor_id, inference_client=inference_client)`。
- **`provider_kwargs: dict | None`** — generic-kwargs bundle handoff (PPO
  pattern, dict 内可含 `WeightsSHM.serialize_for_worker(...)` 返 dict +
  tempfile path str + 任意 picklable param)。 actor_main SHALL 调用
  `build_provider(cfg, actor_id, **provider_kwargs)`。

**互斥约束**:`inference_client` + `provider_kwargs` 两者都 non-None SHALL
raise `ValueError` (二义性 — paradigm 不应同时挑两个 escape hatch)。 两者
都 None → build_provider 走 legacy `(cfg, actor_id)` 签名 (AZ current
pattern,parent 不需 handoff)。

**spawn-safe 约束**:`provider_kwargs` dict 内所有 value SHALL picklable by
`mp.Process` spawn ctx (pickle protocol 4+)。 包括 `_SHMSlot` 实例 (内部
`__getstate__` 实现) / `WeightsSHM.serialize_for_worker` 返 dict / `mp.Queue` /
`mp.Event` / `mp.Lock` / dict / list / tuple / str / int / float / bytes /
Path str。 禁止 torch `nn.Module` / open file handle / socket / un-pickleable
thread state / cgo handles。 actor_main 不 validate 内部 schema (下沉到
paradigm 端 build_provider 实现, paradigm 自行 schema check)。

**Rationale**:
- AB13 把 parent → child spawn-safe 资源传递 surface 限定为两个清晰显式
  字段, 避免 env var-based 隐式状态传递 (与 user 2026-05-23 决策
  `feedback_cfg_driven_only` 对齐 — runtime 行为由 cfg 决定, 不走 env
  var)。
- `inference_client` 与 `provider_kwargs` 是对偶 escape hatch:single object
  vs bundle dict;future paradigm 任挑一个 fit, 不需要再扩 actor_main
  signature 加 paradigm-specific 字段。
- 互斥语义清晰 — DMC pattern 已成立 (`inference_client`), PPO pattern 新
  接通 (`provider_kwargs`);后续 paradigm onboarding 看 dispatch matrix
  挑路径, actor_main 不感知 paradigm 名字。

**Failure mode if violated**:
- 两者都给 → 早 fail ValueError, 暴露 paradigm dispatch bug, 避免 silent
  优先级一个吃掉另一个。
- spawn-unsafe value 漏进 `provider_kwargs` → `mp.Process` spawn 抛
  `pickle.PicklingError` 或 `TypeError`, 在 caller stack 暴露 — actor_main
  不主动检测 (下沉到 paradigm 端约束)。

**Code references** (post-implement):
- `training/core/actor/actor_process.py:actor_main` — provider_kwargs 字段 +
  互斥 raise + dispatch
- `training/paradigms/dmc/collector.py:_bootstrap` (line 235) —
  `inference_client` pattern (AB13 第 1 escape hatch)
- `training/paradigms/ppo/_async.py:PPOAsyncCollector.__init__` —
  `provider_kwargs` pattern (AB13 第 2 escape hatch)
- `training/paradigms/ppo/mp_factories.py:build_provider` — 显式 kwargs
  签名接 `weights_shm_info` + `network_blueprint_path`
