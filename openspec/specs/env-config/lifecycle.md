---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: env-config
subtopic: lifecycle
---

# Lifecycle — `__init__` / reset / step / clone / scenario injection

> 本 subtopic 锚定 `GicgEnv` 的生命周期约定 + scenario cfg 字段 -
> 构造期接受的 cfg(team / pool / deck_padding / fix_dice / obs_mask
> / max_rounds 等)、reset 的 cheapness、step 的 4-tuple 契约、clone
> 的语义、close + context manager。
>
> 源 truth:`gicg_env/env.py::GicgEnv.__init__` / `reset` / `step` /
> `clone` / `close`。

## 1. Scope

本 subtopic 覆盖:

- `__init__` cfg 字段 + 默认值
- `reset(seed, deck_seeds=None)` 语义
- `step(action_idx)` 4-tuple 契约(行为细节)
- `clone()` 深拷贝 + shared static ruleset 规则
- `close()` + `__enter__` / `__exit__` context manager
- Pool / deck_padding / fix_dice / obs_mask cfg 字段语义
- Public properties(`obs_size` / `current_player` / `acting_player` /
  `done` / `team_0` / `team_1` / `data_dir` / `card_pool`)

不覆盖:

- Engine 端 `GameNew` / `reset_dynamic` 实现 —
  [`engine-runtime`](../engine-runtime/spec.md)
- C API binding 层 — [`engine-capi`](../engine-capi/spec.md)
- ADR-0011 pool versioning 设计推导 —
  [`changes/archive/0011-pool-versioning`](../../changes/archive/0011-pool-versioning/)

## 2. `__init__` cfg

### 2.1 Signature

```python
GicgEnv(
    team_0,                  # list[str] — required
    team_1,                  # list[str] — required
    card_pool=None,          # list[str] | None
    seed=42,                 # int
    data_dir=None,           # str | None
    lib_path=None,           # str | None
    obs_config=None,         # dict | None
    reward_shaping=None,     # None | dict | RewardShaping
    max_rounds=0,            # int; 0 = engine default
    fix_dice=None,           # list[int] | None — debug aid
    obs_mask=None,           # list[str] | None
    deck_padding=None,       # dict | None — ADR-0011
    pool=None,               # str | list[str] | None — ADR-0011
)
```

### 2.2 SHALL invariants

1. `team_0` + `team_1` SHALL be required positional/keyword args,值
   为 `list[str]` 字符 ID(`'赤蝶'` / `'墨客'` / ...)。

2. 未声明 kwarg SHALL be rejected by Python signature(no
   `**kwargs` catchall)。新 cfg 字段加入 SHALL 走 OpenSpec change。

3. `__init__` SHALL persist cfg(`_team_0` / `_team_1` / `_card_pool`
   / `_obs_config` / `_reward_shaping` / `_max_rounds` / `_fix_dice`
   / `_deck_padding` / `_pool`)给 `reset` / `clone` 复用。

4. `obs_config` mutable dict SHALL be **defensively copied**(`dict(arg)`)
   on persist — caller mutation 不影响 env。

5. `__init__` SHALL invoke `self._engine.new_game(...)` 一次,SHALL
   NOT lazy-init。后续 `reset(seed)` 是 cheap dynamic-only re-roll(无
   DSL reload)。

6. `__init__` SHALL cache `_static_obs_size` / `_dynamic_obs_size` /
   `_static_obs` 在构造期一次性查询,后续 `reset` SHALL NOT 重新查
   (static 数据 per-game 不变)。

7. Counter normalize meta(`_slot_min` / `_slot_max` / `_slot_denom`)
   SHALL be derived from `static_obs[:OBS_COUNTER_SLOTS * 3]` reshape
   `(OBS_COUNTER_SLOTS, 3)` 后切前 2 列 + max(diff, 1.0) floor。

## 3. Scenario cfg fields

### 3.1 `pool`(ADR-0011)

- `pool=None` → engine default `["v_legacy"]`(legacy 卡池)
- `pool="v_legacy"` 单字符串 → 单 pool
- `pool=["v_legacy", "spike"]` list → sibling-pool union(manifest fold)
- 任一 pool ID SHALL 存在于 `data/pools/` 目录

### 3.2 `deck_padding`(ADR-0011)

- `deck_padding=None` → 无 filler(deck length = eligible-card count)
- `deck_padding={"card": "碌碌无为", "target_size": 15}` → filler 卡
  指定 + 目标 deck size。Filler 卡 SHALL be a valid card ID in current
  pool union。

### 3.3 `fix_dice`

- `fix_dice=None` → engine 端 random dice roll
- `fix_dice=[8 ints of color counts]` → 每回合 force dice 为该分布
  (debug / regression test 用)

### 3.4 `obs_mask`

- 详 [`./obs.md`](./obs.md) §4

### 3.5 `max_rounds`

- `max_rounds=0` → engine default(当前 10 rounds)
- `max_rounds=N > 0` → cap rounds at N(curriculum / smoke 测试用)

### 3.6 SHALL invariants

1. Pool union 由 manifest fold(`data/pools/<id>/manifest.toml`)合并,
   `pool` 字段语义 SHALL track ADR-0011。

2. `disjoint_teams=True`(ADR-0011 mirror-match)由 engine 自动启用
   when teams 完全相同,Python 端 SHALL NOT 二次注册。

3. `card_pool` 与 `pool` 二选一(deprecated `card_pool` 仍接受向后
   兼容)。`pool` 是新 spec source of truth。

## 4. `reset(seed, deck_seeds=None)`

### 4.1 SHALL invariants

1. `reset(seed=42)` SHALL re-roll dynamic state(dice / deck shuffle /
   obs perm)with single seed,**SHALL NOT** reload DSL or rebuild
   teams。

2. `reset(seed=42, deck_seeds=(p0_seed, p1_seed))` SHALL split deck
   Fisher-Yates seed per player — 用于 ablation(同 dice seed 但不
   同 deck order)。

3. `reset` SHALL return initial dynamic obs(`_get_obs()`)= 后续
   `step` 第一次的输入。

4. `reset` SHALL be cheap relative to `__init__`(no DSL reload, no
   engine handle re-create)— matchup 跑 N 局 reuse 同一 env。

## 5. `step(action_idx)` 4-tuple

详 [`./action.md`](./action.md) §6 + [`./reward.md`](./reward.md) +
[`./obs.md`](./obs.md) §3.2.5。本节锚定 lifecycle 视角。

### 5.1 SHALL invariants

1. `step` SHALL return `(obs, reward, done, info)` 4-tuple,顺序
   stable across paradigm。

2. Terminal step `obs` SHALL be `np.zeros(self.obs_size, dtype=np.float32)`
   占位(语义无效,消费方 guard with `done`)。

3. `info` SHALL always contain `winner` + `turn`;terminal 加 `z`;
   pending target 加 `need_target=True`。

4. `info` SHALL NOT contain `z` on non-terminal step(misuse 防护)。

## 6. `clone()`

### 6.1 SHALL invariants

1. `clone()` SHALL return new `GicgEnv` instance with **deep-copied
   engine handle**(via `self._engine.clone()`)+ **shared static
   ruleset**(team / card_pool / obs_config / reward_shaping by
   reference)。

2. Cloned env SHALL be steppable independent — `step` on clone SHALL
   NOT affect original engine state。

3. `_mask_slots_per_perspective` SHALL be reused by reference(immutable
   pre-computed ndarrays)。

4. `_deck_padding` mutable dict SHALL be defensively `dict(...)` copy
   (与 `__init__` 一致)。`_pool` list SHALL be defensively `list(...)`
   copy。

## 7. `close()` + context manager

### 7.1 SHALL invariants

1. `close()` SHALL release engine handle via `self._engine.close()`。
   后续 method call 行为 SHALL be undefined(engine handle dangling)—
   调用方责任不 leak。

2. `__enter__` SHALL return `self`,`__exit__(*args)` SHALL call
   `close()`。`with GicgEnv(...) as env:` 是推荐 pattern,exception
   safe。

3. Matchup runner / arena SHALL `try: ... finally: env.close()` 保
   证多局后回收。

## 8. Public properties

### 8.1 SHALL invariants

1. `obs_size` → `_dynamic_obs_size`(int)。
2. `static_obs_size` → `_static_obs_size`(int)。
3. `static_obs` → cached ndarray(read-only by convention)。
4. `current_player` / `acting_player` → engine `acting_player`(0/1)。
   两者 alias,`acting_player` 在 search 代码中是 canonical name。
5. `has_pending` → bool,pending target / forced switch 状态。
6. `done` → bool,engine terminal 状态。
7. `team_0` / `team_1` → defensive `list(...)` copies。
8. `data_dir` / `card_pool` → 构造期值(后者 defensive copy)。

`current_player` vs `acting_player` 语义一致(后者更明确表达 "pending
forced switch 时实际 owe decision 的玩家"),search 代码 SHALL 用
`acting_player`(详 docstring)。

## 9. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 3 + SHALL 4 + SHALL 9 + SHALL 10
  — lifecycle / scenario / pool 锚点
- [`./obs.md`](./obs.md) — `_get_obs` 内部实现
- [`./action.md`](./action.md) — `step` 路由 + IS-MCTS injection
- [`./reward.md`](./reward.md) — reward 模式
- [`engine-runtime`](../engine-runtime/spec.md) — `GameNew` /
  `reset_dynamic` engine 端
- [`changes/archive/0011-pool-versioning`](../../changes/archive/0011-pool-versioning/) —
  pool / deck_padding / disjoint_teams cfg 字段

## 10. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`gicg_env/env.py::GicgEnv` shipped code
- **Known gap**:`obs_config` cfg 字段(枚举 mask / phase mask 等)
  当前实施散在 engine 端,Python 仅透传 dict;未 spec 出可接受的
  key 集合 — follow-up by `engine-runtime` capability。
