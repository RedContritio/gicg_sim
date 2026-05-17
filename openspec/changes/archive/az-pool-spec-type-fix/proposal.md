# az-pool-spec-type-fix — 修 AZ collector/policy 3 处 dict→CardPoolSpec 误传

**Status:** Active change(implementation complete,pending archive)
**Date opened:** 2026-05-17
**Supersedes:** None
**Affected specs:**
- `paradigm-az/spec.md`(MODIFY A5 — add A5.4 invariant on pool spec construction discipline)

## Why

`paradigm-smoke-full-tier` (#6) D-601 baseline 5 paradigm 触发后 SF-105 暴露 AZ smoke_full SKIP 根因:

`training/paradigms/az/collector.py:72` `AZSelfPlayCollector.__init__`:

```python
self._card_pool_spec = resolve_pool_refs(cfg.scenario)
```

`resolve_pool_refs()`(`pool_spec.py:11`)return `dict[int, list[int]]`,而下游
`sample_hidden_state()`(`determinize.py:138-148`)expects `CardPoolSpec`
protocol(`.sample_opponent_deck(rng, pub)` method)。`play_self_game` →
`mcts_search` → `sample_hidden_state` 链路 runtime 报:

```
AttributeError: 'dict' object has no attribute 'sample_opponent_deck'
```

→ AZ smoke_full 测试无法运行 + 任何 selfplay run 启动后立即 crash。

**Root cause**:同一 dict→spec 错误在 AZ 内出现 **3 处**(grep `resolve_pool_refs(cfg.scenario)`):

1. `collector.py:72` — `AZSelfPlayCollector.__init__` ← smoke_full path
2. `collector.py:172` — `_az_build_policy`(async actor 工厂)← AZAsyncCollector path
3. `paradigm.py:152` — `AZParadigm.make_episode_policy` ← protocol-level test/async path

而正确用法 `make_pool_spec(scenario, resolve_pool_refs(scenario))` 已在
`inference_worker.py:87-88` proven。3 处违规独立 copy/paste 同 anti-pattern。

## What

**Fix**(centralize pool construction):

- 3 处违规 site 全部走 `make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))`
- `make_pool_spec()` 已存在(`pool_spec.py:38-44`),handles `disjoint_teams=True`
  → `PerOpponentPool`,else → `SharedFixedPool`
- import 在 3 个文件加 `make_pool_spec`(已 import `resolve_pool_refs`,同 module)

**Test status update**(原计划 unskip → 改为 rewrite skip reason):

- `training/tests/test_az_smoke_full.py`:原计划 remove `@pytest.mark.skip`
  decorator;baseline verify 暴露 resume-phase 第三 bug 后 → keep `pytest.skip`
  但 reason 切到新 follow-up `az-resume-shape-fix`;docstring 详记 partial
  unblock 现状(train PASS / resume fail)。本 change 不解锁 test。

**Bundled fix discovered during smoke_full baseline verify**:

- `training/paradigms/az/network.py:280-281`(`AZNetwork.game_start`):wrapper
  drops `self._agent.game_start(static_obs)` return value(annotated `-> None`),
  但 `selfplay.py:54,64` 把它接为 `game_static` → push 到 buffer
  → `buffer.py:74` `AttributeError: 'NoneType' object has no attribute 'keys'`。
  修法:wrapper return `self._agent.game_start(...)`,annotate `-> dict`,与
  `AgentBase.game_start` contract 一致。1 line bundled。
  
  Bundle 理由:同一 smoke_full 启用 path 的 sequential blocker,scope 1 LOC,
  独立 change 开销远大于 bundle 收益(per ppo-cfg-shape-alignment T2 bundled fix 先例)。

**Spec delta**:

- `paradigm-az/spec.md` A5(Collector)新增 **A5.4** SHALL invariant:
  > AZ paradigm 内任何持有 `card_pool_spec` 的 site SHALL construct via
  > `make_pool_spec(scenario, resolve_pool_refs(scenario))`,SHALL NOT 直接
  > 把 `resolve_pool_refs()` 的 dict return 当作 spec 传给 `sample_hidden_state`
  > / MCTS 链路(`determinize.CardPoolSpec` protocol violation,运行时
  > AttributeError)。Single point of construction discipline。

## Affected specs

- `paradigm-az/spec.md` ADD A5.4(pool spec construction discipline)

## Out of scope

- 4 个 smoke_full follow-up 中的其他 3 个(`ppo-rollout-card-pool-none-fix` /
  `cfr-driver-buffer-multihead-fix` / `bc-smoke-dataset-fixture`)— 各自独立 change
- `resolve_pool_refs()` return 改 spec 类型(API breakage,全 caller 改;本
  change 选最小侵入:在 3 个 caller 加 wrap,保持 helper 责任不变)

## Verification

- `pytest training/tests/test_az_smoke_full.py -m smoke_full` train-phase
  subprocess PASS(`final: step=30 frames=1025 episodes=30 train_steps=29
  wall_s=25.2`;30 ckpts + latest.pt + metrics.jsonl 全 OK)— A1.6.1 +
  A1.6.2 contract satisfied。Resume-phase subprocess fail at adam.py:547
  `_single_tensor_adam` with `RuntimeError: output with shape [1, 64] doesn't
  match the broadcast shape [1832, 64]` — pre-existing AZ ckpt-resume
  optimizer state shape mismatch,OUT of "wrap with make_pool_spec" scope →
  new follow-up **`az-resume-shape-fix`** queued。
- `pytest training/tests/test_az_*.py training/tests/test_determinize.py`(non
  smoke_full): 72/72 baseline pass(无 regression)
- Full sweep `pytest -n 4 training/tests/`(ignoring 4 known-bad per memory
  `project_pre_existing_sandbox_failures_2026_05_17`):995 passed / 3 skipped
  / 0 failed
- `tools/_meta/check_openspec_indices` pass + `tools/_meta/check_line_limits` pass
