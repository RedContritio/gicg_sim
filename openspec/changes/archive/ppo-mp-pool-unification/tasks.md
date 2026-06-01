---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: ppo-mp-pool-unification
---

# Tasks — PPO mp pool unification

> 单 session subagent-driven implementation。Phase 1 + 2 + 3 一次性 ship。

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact
  - `proposal.md` (本 change why/what/scope)
  - `design.md` (provider_kwargs 字段设计 + handoff bundle 选择 + AB13 wording)
  - `tasks.md` (本文件)
  - `specs/training-architecture/actor-backend.md` (ADD AB13)
  - **LOC**:~700 artifact only
  - **依赖**:无

## Phase 2 — Implementation

- [x] **T1**:扩 `actor_main` 加 `provider_kwargs` 字段
  - **File**:`training/core/actor/actor_process.py`
  - **改动**:
    - signature 加 `provider_kwargs: Optional[dict] = None` (位置:与
      `inference_client` 相邻, line 80 下)
    - docstring update — 加 calling convention 第 3 类 (PPO pattern)
      + 互斥说明
    - dispatch block 改:
      ```python
      if inference_client is not None and provider_kwargs is not None:
          raise ValueError(...)
      if inference_client is not None:
          provider = build_provider(cfg, actor_id, inference_client=inference_client)
      elif provider_kwargs:
          provider = build_provider(cfg, actor_id, **provider_kwargs)
      else:
          provider = build_provider(cfg, actor_id)
      ```
  - **LOC**:~20 net (+25 docstring/dispatch -5 旧 2 分支)
  - **依赖**:T0

- [x] **T2**:新建 `training/paradigms/ppo/mp_factories.py`
  - **改动**:
    - 从 `_async.py` 搬 5 件套 + `_PPOActorProvider`
    - `build_opp_registry(cfg)` — 删 `os.environ.get(_ENV_OPPONENT, 'random')`,
      改读 `cfg.paradigm['rollout']['rollout_opponent']` (dict 形态);
      `extra` 改成从 cfg 算
    - `spec_sampler(cfg, actor_id)` — 删 env var read, 改读
      `cfg.paradigm['rollout']['rollout_opponent']`
    - `build_provider(cfg, actor_id, *, weights_shm_info, network_blueprint_path)`
      — 删 `os.environ.get(_ENV_*)`, 改用显式 kwargs;`tempfile` /
      `pickle.load(net_path)` 路径不变 (network blueprint 仍 tempfile)
    - 模块开头 docstring 写 DMC 模板对齐说明 + cfg-driven (无 env var)
  - **LOC**:~160
  - **依赖**:T0

- [x] **T3**:改 `training/paradigms/ppo/_async.py` 缩到 ~150 LOC
  - **改动**:
    - 删 `_ENV_SHM_PATH` / `_ENV_NET_PATH` / `_ENV_OPPONENT` 3 常量
    - 删 build_env_factory / build_opp_registry / build_policy / build_provider
      / spec_sampler / `_PPOActorProvider` / `_SPEC_COUNTERS` / `_derive_seed`
      (已搬到 mp_factories)
    - `__init__` 内构造 `weights_shm_info` + `network_blueprint_path` 变量,
      传入 `provider_kwargs` (via `actor_kwargs_factory`)
    - `start_actors` dotted path 改指 `training.paradigms.ppo.mp_factories.*`
    - `close` 删 env var pop loop
    - docstring update — 描述 DMC 模板对齐 + cfg-driven handoff
  - **LOC**:~150 (from 300)
  - **依赖**:T1, T2

- [x] **T4**:改 `training/tests/test_ppo_async.py`
  - **改动**:
    - 4 个 test import 路径:`from training.paradigms.ppo._async import
      build_policy / spec_sampler / _PPOActorProvider / _ENV_OPPONENT /
      _SPEC_COUNTERS` → `from training.paradigms.ppo.mp_factories import ...`
      (`_ENV_OPPONENT` 完全删, 用 cfg stub 替代)
    - `test_ppo_async_spec_sampler_monotonic_and_self_to_random`:
      - 删 `os.environ[_ENV_OPPONENT] = 'self'` setup
      - 用 cfg stub `_AsyncCfg.paradigm = {'rollout': {'rollout_opponent': 'self'}, ...}`
        测试 'self' → 'random' 退化
      - 用 cfg stub `_AsyncCfg.paradigm = {'rollout': {'rollout_opponent': 'random'}, ...}`
        测试 default opp_id
    - 加 `test_ppo_async_provider_kwargs_handoff`:
      mock build_provider → 验 actor_main 走 provider_kwargs path 时
      build_provider 收到 kwargs 透传
      (走 in-proc actor_main + mock provider, 不真 spawn)
    - 加 `test_ppo_async_provider_kwargs_inference_client_mutex`:
      验 两者都给 → ValueError
  - **LOC**:~50 net (+30 新 test +10 改 sampler test +10 改 import)
  - **依赖**:T1, T2, T3

- [x] **T5**:新建 `training/tests/test_ppo_async_mp_e2e.py` (smoke_full)
  - **改动**:
    - pytest marker `@pytest.mark.smoke_full`
    - spawn 2 actor + run 1-2 episode + verify weight sync + clean shutdown
    - 仿 DMC tests 的 e2e pattern (`test_dmc_async_collector.py` /
      `test_go_subprocess_1ep_smoke.py`)
    - 1 ep 1 actor 用 PPOAsyncCollector 真接 mp;cfg 用 small scenario
      (smoke 6-card pool / max_rounds=2)
  - **LOC**:~120
  - **依赖**:T3, T4

## Phase 3 — Verify

- [x] **T6**:`pytest test_ppo_async.py` + `test_ppo_async_mp_e2e.py syntactic only`
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/test_ppo_async.py \
      training/core/actor/tests/ -q
    ```
  - **Pass**:0 new failures vs baseline
  - **依赖**:T1-T5

- [x] **T7**:`pytest -m smoke -k ppo`
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -m smoke training/tests/ -q -k ppo
    ```
  - **Pass**:PPO smoke 不 break
  - **依赖**:T6

- [x] **T8**:`ruff format` + line limit hook 验
  - **Command**:
    ```bash
    .venv/bin/ruff format training/paradigms/ppo/mp_factories.py \
      training/paradigms/ppo/_async.py \
      training/core/actor/actor_process.py \
      training/tests/test_ppo_async.py \
      training/tests/test_ppo_async_mp_e2e.py
    .venv/bin/python -m tools._meta.check_line_limits | grep -E "(ppo|actor_process)" || echo "PASS"
    ```
  - **Pass**:format 0 changes (已 format-clean), line limit 全文件 ≤ 阈值
  - **依赖**:T7

- [x] **T9**:openspec validate
  - **Command**:`.venv/bin/python -m tools._meta.check_openspec_indices --staged`
  - **Pass**:`ppo-mp-pool-unification/specs/training-architecture/spec.md`
    格式 OK
  - **依赖**:T0 (artifact 落盘)

## 总进度

- Phase 1:1/1
- Phase 2:5/5
- Phase 3:4/4
- 总计:10/10

## 依赖图

```
T0 (propose: 4 artifacts)
  ├── T1 (actor_main provider_kwargs)
  │    └── T3 (_async.py cleanup)
  │         └── T5 (mp e2e test)
  ├── T2 (mp_factories.py new)
  │    └── T3
  ├── T4 (test_ppo_async.py update) ← T1, T2, T3
  ├── T6 (pytest unit verify) ← T1-T5
  ├── T7 (pytest smoke -k ppo)
  ├── T8 (ruff + line limit)
  └── T9 (openspec validate)
```
