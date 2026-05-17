---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: env-config
subtopic: reward
---

# Reward — Terminal signal + 可选 RewardShaping dense delta

> 本 subtopic 锚定 `GicgEnv` 端 reward 接口契约 — paradigm-agnostic
> terminal signal(`info['z']`)与可选 per-step dense shaping
> (`RewardShaping` Δ RewardEvents)。本 spec **不** 治理具体 shaping
> 公式与系数(各 paradigm dossier 承接),仅锚定接口与正确性约束。
>
> 源 truth:`gicg_env/env.py::step` + `gicg_env/env.py::_terminal_z` +
> `gicg_env/env_reward.py`。

## 1. Scope

本 subtopic 覆盖:

- Paradigm-agnostic terminal `info['z']` 契约(P0 perspective ±1 / 0)
- Per-step `reward` 返回值的两种模式(disabled / shaping)
- `RewardShaping` dataclass 字段与 `from_arg` 接受 input 类型
- `compute_shaped_reward` Δ-events × coefs 公式
- Strict terminal guard(`_terminal_z` raises on invalid winner code)
- Perspective-of-actor 约定

不覆盖:

- 各 paradigm 选择哪些 coef / 系数比例(AZ D5 / PPO 1.0 vs 1.1 / DMC
  stage-coef)— 各 paradigm dossier
- 引擎侧 `RewardEvents` accumulator 字段定义 —
  `gicg_env._constants.REWARD_EVENTS_FIELDS` + engine-dsl
- 网络侧 value head loss target(`z` consumed by trainer)—
  `network-architecture/loss`

## 2. Terminal signal — paradigm-agnostic

### 2.1 SHALL invariants

1. `step()` SHALL include `info['z']` **only** on terminal step
   (`done=True`)。Non-terminal step `info` SHALL NOT contain `z`
   key。

2. `info['z']` SHALL be P0-perspective outcome:
   - `+1.0` if engine `winner == 0`(P0 wins)
   - `-1.0` if engine `winner == 1`(P1 wins)
   - `0.0` if engine `winner == 2`(draw)

3. `_terminal_z(winner)` SHALL raise `ValueError` on `winner == -1`
   (game not yet terminated)or any unexpected value — caller SHALL
   guard with `done=True` first。

4. `info` SHALL always include `winner`(engine code:0/1/2 or -1
   for non-terminal)+ `turn`(`self._engine.turn`)。

5. Non-terminal `info['winner']` SHALL be `-1`(SHALL NOT use 0 / 1
   sentinel — `-1` 与 engine in-progress code 对齐)。

## 3. Per-step `reward` return value

### 3.1 Two modes

`GicgEnv.__init__(reward_shaping=...)` 接受三类输入(由
`RewardShaping.from_arg` 归一化):

- `None` → shaping disabled,`step()` SHALL return `reward = 0.0`
  paradigm 通过 terminal `info['z']` 读 ±1 / 0(AZ D5 决策的默认)
- `RewardShaping(...)` instance → pass-through
- `dict` with valid field names → `RewardShaping(**arg)`

### 3.2 SHALL invariants

1. `reward_shaping=None` 时 `step()` SHALL return `reward=0.0` 在所
   有 step(含 terminal)。`info['z']` 仍按 §2.2 提供。

2. `reward_shaping=<RewardShaping>` 时 `step()` SHALL return Δ-events
   reward(详 §4),从 **acting player perspective**(`me =
   self._engine.acting_player` snapshot **before** step)。

3. `from_arg(dict)` SHALL `raise ValueError` 如果 dict 含未声明字段
   (典型场景:misspelled coef name 会被静默丢 0 — 严格 raise 防误
   配)。

4. `RewardShaping` dataclass SHALL be **frozen**(`@dataclass(frozen=True)`),
   coef 集合 SHALL NOT 在 env 生命周期内 mutate。

## 4. RewardShaping — fields + formula

### 4.1 Fields

`RewardShaping` 字段(全部默认 0.0):

- `hp_delta` — coef on `damage_dealt`(自己造成的伤害)
- `hp_taken_penalty` — coef on `damage_received`(自己受到的伤害,
  在公式中带负号)
- `kill_bonus` — coef on `kills`
- `death_penalty` — coef on `deaths`(带负号)
- `terminal_win` — flat bonus 当 `me` won at done
- `terminal_loss` — flat penalty 当 `me` lost at done(带负号)

### 4.2 Formula

`compute_shaped_reward(shaping, events_before, events_after, done,
winner, me)`:

```
d = events_after - events_before                  # Δ vector per field
r = shaping.hp_delta * d[damage_dealt]
  - shaping.hp_taken_penalty * d[damage_received]
  + shaping.kill_bonus * d[kills]
  - shaping.death_penalty * d[deaths]

if done:
    if winner == me:        r += shaping.terminal_win
    elif winner == 1 - me:  r -= shaping.terminal_loss
    # winner == 2 (draw) → no terminal bonus(symmetric)
```

### 4.3 SHALL invariants

1. Δ SHALL be computed in `float64` 中间(int32 events 转换),返回
   值 cast 到 Python `float`,精度不丢。

2. `winner == 2`(draw)at `done=True` SHALL NOT apply terminal bonus
   either way(symmetric on symmetric outcome)。

3. `compute_shaped_reward` SHALL only be invoked when `shaping is not
   None`;`None` 是 wire-disabled 信号,SHALL short-circuit 在 call
   site(`env.step` `_score_reward` 已实施)。

4. `me` 是 step **开始时**的 acting player,SHALL be snapshot **before**
   `self._engine.step(...)` invocation。否则 step 改变 acting player
   后 reward 透视错位。

## 5. RewardEvents accumulator

### 5.1 SHALL invariants

1. Env SHALL call `self._engine.get_reward_events(me)` only when
   shaping is enabled — `reward_shaping is None` 时 cgo round-trip SHALL
   被 skip(AZ hot path 性能考量)。

2. `RewardEvents` 字段顺序 SHALL track `gicg_env._constants.REWARD_EVENTS_FIELDS`
   canonical tuple,字段 reorder 在 Go 端 propagate 到 Python `_IDX`
   dict(via `enumerate`)— `damage_dealt` / `damage_received` /
   `kills` / `deaths` 等 SHALL NOT 用 hard-coded index。

3. `reward_events(player)` query method(`_QueryMixin`)SHALL expose
   accumulator 给外部 evaluator(F3-F5 greedy 用,paradigm 之外仍可
   读)。

## 6. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 7 + SHALL 8 — reward signal
  锚点
- [`./lifecycle.md`](./lifecycle.md) — `reward_shaping` cfg 字段注入
- [`network-architecture/loss`](../network-architecture/loss.md) —
  value head MSE target consumes `z`
- [`engine-dsl`](../engine-dsl/spec.md) — engine `RewardEvents`
  accumulator 字段在 DSL 端的语义
- ADR-0005 §D5 — AZ 改纯终局 ±1 决策(本 spec disabled mode 的默认)
- Paradigm dossiers — 各 paradigm 选用的具体 coef 值(P2 落地)

## 7. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`gicg_env/env.py::_terminal_z` / `_score_reward` +
  `env_reward.py`
- **Known gap**:`RewardShaping` 只覆盖 4 个 events 字段(damage
  dealt/received/kills/deaths)+ 2 个 terminal — 引擎 14 字段中其余
  10 个(heal / shield_absorbed / reactions_* / energy_overflow /
  ap_waste 等)目前由 GreedyPlayer F3-F5 直接消费,**未** 在
  `RewardShaping` 公式表达。若 paradigm 需要扩展,SHALL 走 OpenSpec
  change 加字段。
