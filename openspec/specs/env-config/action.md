---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: env-config
subtopic: action
---

# Action — Legal actions / mask / IS-MCTS injection / step routing

> 本 subtopic 锚定 `GicgEnv` 端 action 数据契约 — legal action 枚举、
> dice payment 展开、legal mask、IS-MCTS determinization injection 入
> 口、`step` / `step_target` 路由。
>
> 源 truth:`gicg_env/env_action.py` + `env_query.py` + `env.py::step`。

## 1. Scope

本 subtopic 覆盖:

- Legal action enumeration(kinds + dice payments)
- Per-decision action features(refs / identities / labels)
- Legal mask boolean ndarray
- IS-MCTS determinization injection(`set_player_dice` /
  `set_player_hand` / `set_player_deck`)
- Snapshot / restore / log_suspend / log_resume
- `step(action_idx)` vs `step_target(action_idx)` 路由

不覆盖:

- ActionKind 枚举数值与引擎侧语义 — [`engine-actions`](../engine-actions/spec.md)
- Dice payment enumerate 算法 — [`engine-dice`](../engine-dice/spec.md)
- 网络侧 action embedding 与 policy head — [`network-architecture/heads`](../network-architecture/heads.md)

## 2. Legal action enumeration

### 2.1 SHALL invariants

1. `get_legal_actions()` SHALL return `(kinds, payments)` tuple 透传
   `self._engine.get_legal_actions()`。`kinds` 为 list[ActionKind int],
   长度 = `n_legal`(含 dice payment 展开)。

2. `get_legal_action_payments()` SHALL return per-legal-action dice
   payment 矩阵。同一 logical action 因 dice 槽位 fanout 可展开为多
   行(e.g. "cost [1 pyro, 2 any]" 在 8 omni pool 下 fan 为 28
   payment 行)。

3. `get_action_identities()` SHALL return `(n_legal, 5)` int32,5
   列为 `(kind, primary_arg, secondary_arg, tertiary_arg, payment_id)`。
   identity tuple SHALL be **stable across same engine state**(相同
   state 二次调用顺序一致),paradigm 用于 dedup / replay。

4. `get_action_refs()` SHALL return per-legal-action ref ndarray,
   用于 policy head pointer-net gather(`SKILL` / `CARD` /
   `SWITCH` / `END_TURN` 四类 + dice payment)。

5. `get_action_labels()` SHALL return `list[(kind, name, slot)]`,
   只用于 debug / replay,SHALL NOT 被网络消费。

### 2.2 Order stability

Legal action 顺序在同一 state 下 SHALL be deterministic —
`get_legal_actions()` 二次调用返回 byte-identical 结果。paradigm
依赖这个 invariant 做 IS-MCTS determinization 后 legal mask 对齐。

## 3. Legal mask

### 3.1 SHALL invariants

1. `get_legal_mask(max_actions)` SHALL return `bool ndarray[max_actions]`
   with `mask[:n_legal] = True`,其余 `False`。

2. `n_legal > max_actions` 时 mask SHALL truncate(取前 max_actions
   个);policy head 端责任检测 truncation(paradigm dossier 治理具
   体处理策略)。

3. Mask SHALL be paradigm-agnostic — AZ MCTS expansion / CFR regret
   normalize / PPO logit mask 共用同一函数。

## 4. IS-MCTS determinization injection

### 4.1 Hidden state SHALL be injectable

Env SHALL expose 三个 setter,用于 IS-MCTS 注入对手 hypothetical
state(self play 时同样用于 root determinization):

- `set_player_dice(player, counts)` — overwrite per-color dice pool
  (counts 为 length-8 ndarray:fire / ice / water / electro / geo /
  anemo / dendro / omni)
- `set_player_hand(player, refs)` — overwrite hand cards by ref list
- `set_player_deck(player, refs)` — overwrite deck;`refs[0]` 为 top
  of deck

### 4.2 SHALL invariants

1. Setter SHALL only mutate hidden state(dice / hand / deck),SHALL
   NOT 触发 hook / counter 改动。Engine 端 sandbox 保证。

2. Setter 调用时机 SHALL be **between `step()` calls**,不在 step 中
   断点注入。MCTS pattern:`snapshot → set_player_* → rollout →
   restore`。

3. Determinization injection SHALL NOT 影响 obs perspective —
   `_get_obs` 仍按当前 `acting_player` 视角 mask 不可见信息。

## 5. Snapshot / restore / log control

### 5.1 SHALL invariants

1. `snapshot()` SHALL return opaque `snap_id` (int handle) 给后续
   `restore` / `snapshot_free` 用。Handle 生命周期由调用方管理,
   SHALL `snapshot_free(snap_id)` 释放。

2. `restore(snap_id)` SHALL restore engine state byte-identical to
   `snapshot()` 时刻。后续 `get_legal_actions` / `_get_obs` 结果与
   snapshot 时一致。

3. `log_suspend()` / `log_resume()` SHALL bracket MCTS forward sim,
   避免 rollout 事件写入 replay log + 节省 per-event format 开销。
   suspended 期间事件丢弃,resume 后不补。

4. `clone()` SHALL return a deep-copied env with shared static
   ruleset(ruleset / team / pool / obs_config / reward_shaping by
   reference share OK)+ independent engine handle。Clone 后两 env
   可独立 step。

## 6. `step` routing — regular vs target

### 6.1 SHALL invariants

1. `step(action_idx)` SHALL dispatch to:
   - `self._engine.step_target(action_idx)` if `self._engine.has_pending`
     (pending card target / forced switch)
   - `self._engine.step(action_idx)` otherwise
   
   路由查询通过 `has_pending` property,SHALL NOT 用 local flag(snapshot
   / restore cycle 会破坏 local flag 一致性)。

2. 若 `step` 返回 `STEP_NEED_TARGET`,`env.step` SHALL return obs +
   reward + `done=False` + `info={'need_target': True, 'winner': -1,
   'turn': self._engine.turn}`,**不** include `z`。

3. 后续 step 调用 SHALL 自动路由到 `step_target`(`has_pending=True`),
   action_idx 现在表示 target choice。matchup runner / arena 视
   `step_info.get('need_target')` 为 raise-on-unsupported(详
   `training/framework/matchup/matchup.py::_play_one`)。

## 7. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 6 + SHALL 11 — legal mask /
  injection 锚点
- [`engine-actions`](../engine-actions/spec.md) — ActionKind 数值
- [`engine-dice`](../engine-dice/spec.md) — dice payment 枚举算法
- [`network-architecture/heads`](../network-architecture/heads.md) —
  policy head pointer-net 消费 action_refs
- [`changes/archive/0004-is-mcts-migration`](../../changes/archive/0004-is-mcts-migration/) —
  IS-MCTS 落地(本 spec injection 入口的起源)

## 8. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`gicg_env/env_action.py` + `env_query.py` +
  `env.py::step`
- **Known gap**:`n_legal > max_actions` 截断策略仅在 paradigm 侧实
  施,本 spec 未约束 truncation warning。
