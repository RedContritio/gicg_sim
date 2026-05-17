---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: env-config
subtopic: obs
---

# Observation — Static / Dynamic / Typed segments / Mask

> 本 subtopic 锚定 `GicgEnv` 端 obs 数据契约 — engine raw int 输出 →
> Python normalize → float32 ndarray。本 spec 仅治理 **env 端的输
> 出格式**,网络侧 encoder 消费由 [`network-architecture/obs`](../network-architecture/obs.md)
> 治理。
>
> 源 truth:`gicg_env/env_obs.py` + `gicg_env/env.py` `__init__` /
> `_get_obs` 实现。

## 1. Scope

本 subtopic 覆盖:

- Static obs 字段(`counter_meta` / `char_skill_refs` / `hook_tokens`)
- Dynamic obs layout(meta / counter_values / card_buckets /
  enemy_sizes / typed segments)
- Python 端 per-slot (min, max) normalize 规则
- ADR-0019 typed obs 段(recent_damage / prepare_skill / modifier_log)
  pass-through float cast
- Partial-observability mask(`obs_mask` cfg)
- Action refs / payments(per-decision features)

不覆盖:

- 网络 encoder shape / embedder 字段消费 — `network-architecture/obs`
- Engine 内 obs 写入实现(`gicg_engine/observation.go`)— `engine-dsl` /
  `engine-capi`

## 2. Static obs

### 2.1 SHALL invariants

1. Static obs SHALL be computed **once per game**(at `__init__` /
   `reset`),通过 `self._engine.get_static_obs()` 读取 + cache 在
   `self._static_obs`。

2. Static obs layout SHALL prefix with `counter_meta[OBS_COUNTER_SLOTS, 3]`,
   3 列分别为 `[min, max, shuffled_sid]`。`OBS_COUNTER_SLOTS = 2 * 6 *
   128 + 2 * 140 + 16 = 1832`(`gicg_env/env_obs.py`)。

3. Env SHALL extract `_slot_min` / `_slot_max` / `_slot_denom =
   max(slot_max - slot_min, 1.0)` 在 `__init__` cache 用于 dynamic
   obs normalize。padding slots(min=max=0)由 denom floor 1.0 防 div0。

4. Env SHALL expose `static_obs_size`(`GameGetStaticObsSize()`)+
   `static_obs`(cached ndarray)+ `get_active_counter_slot_labels` +
   `get_active_hook_labels` 给消费方。

### 2.2 Cross-ref

完整 static obs schema(`counter_meta` / `char_skill_refs` /
`hook_tokens` 三字段)详 [`network-architecture/obs`](../network-architecture/obs.md)
§2 — 本 spec 仅锚定 env 端**透传 + meta 抽取**。

## 3. Dynamic obs

### 3.1 Layout(`gicg_env/env_obs.py::_ObsMixin._get_obs`)

```
[0:3]                                 meta (phase, round, is_my_turn)
[3:3+OBS_COUNTER_SLOTS]               counter values
[c_end:hand_end]                      OBS_HAND_BUCKETS × OBS_MAX_CARD_TYPES card buckets
[hand_end:enemy_end]                  OBS_ENEMY_SIZES enemy size scalars
[enemy_end:rd_end]                    recent damage events (K=8 × 11) — ADR-0019 §B.3c
[rd_end:ps_end]                       prepare skill (2 players × 2)  — ADR-0019 §B.2
[ps_end:ml_end]                       modifier log (K=8 × K_mod=4 × 5) — ADR-0019 §B.3c
```

其中 `OBS_META_SIZE=3` / `OBS_MAX_CARD_TYPES=80` /
`OBS_HAND_BLOCK_SIZE = OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES +
OBS_ENEMY_SIZES`。`OBS_HAND_BUCKETS` / `OBS_ENEMY_SIZES` 从
`training.framework.obs_constants` import,SHALL NOT hard-code(消除
跨文件 drift 风险)。

### 3.2 SHALL invariants

1. Dynamic obs SHALL be computed per `step()` / `reset()` via
   `self._engine.get_dynamic_obs()`,perspective 由 engine 端按当前
   `acting_player` 已处理。

2. Counter values segment SHALL be per-slot normalized:
   `out[c] = (raw[c] - slot_min[c]) / slot_denom[c]`。SHALL NOT 用当
   前 step 的 max(scale 会随 step 漂移)。

3. Card buckets SHALL divide by **fixed ceiling 10.0**(`/10.0`),
   enemy sizes SHALL divide by **fixed ceiling 20.0**(`/20.0`)。
   两个 ceiling 是 invariant of layout,SHALL NOT 随 cfg 变化。

4. Typed segments(recent_damage / prepare_skill / modifier_log)
   SHALL be passed through as float cast **without normalization**(网
   络 embedders 解析 typed int 字段;bulk `/20` 会塌缩
   `player_idx` vs `raw_value` 等正交 axis)。

5. Terminal step(`done=True`)`step()` SHALL return zeros ndarray
   `np.zeros(self.obs_size, dtype=np.float32)` 作为 obs(语义占位,
   消费方 guard with `done` first)。

## 4. Partial-observability mask

### 4.1 Cfg

`obs_mask` 接受 `list[str]` 或 `None`(default fully observable)。
当前唯一支持的 category:

- `"enemy_dice"`:zero out enemy `dice_*` PerPlayer counter slots(env
  端 mask,不改 engine state)

### 4.2 SHALL invariants

1. `obs_mask` SHALL be applied **after** counter-segment normalization,
   **before** return from `_get_obs`。Mask values SHALL be `0.0`。

2. Mask slot index set SHALL be **per-perspective** pre-computed at
   `__init__`(`compute_mask_slots`)。两个 perspective 各自一个
   ndarray of slot indices。`_get_obs` 根据当前 `acting_player` 选择
   index set。

3. Unknown category in `obs_mask` SHALL NOT raise(silent skip),但
   未来扩展时 SHALL 增加 category 验证(P2 follow-up)。

## 5. Per-decision features

### 5.1 SHALL invariants

1. `get_action_refs()` SHALL return per-legal-action refs ndarray
   `(n_legal, ?)`,paradigm 用于 policy head pointer-net gather(详
   [`network-architecture/heads`](../network-architecture/heads.md))。

2. `get_legal_action_payments()` SHALL return per-legal-action dice
   payments,用于 dice combo encoding。Fanout 由引擎枚举,每个
   logical action 可能展开为 n payment 行。

3. `get_action_identities()` SHALL return `(n_legal, 5)` int32 数组
   (kind / 主参 / 次参 / 三参 / payment_id),paradigm-agnostic identity
   tuple 用于跨 step dedup / replay。

4. `get_action_labels()` SHALL return `list[(kind, name, slot)]`,
   human-readable,只用于 debug / replay 渲染,网络 SHALL NOT 消费
   字符串名。

## 6. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 5 — obs typed schema 锚点
- [`network-architecture/obs`](../network-architecture/obs.md) — 网
  络侧 obs schema 消费
- [`engine-capi`](../engine-capi/spec.md) — `GameGetStaticObs` /
  `GameGetDynamicObs` 引擎 C API
- [`changes/archive/0019-dsl-v6-semantic-engine`](../../changes/archive/0019-dsl-v6-semantic-engine/) —
  Typed obs 段引入

## 7. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`gicg_env/env.py` + `gicg_env/env_obs.py`
- **Known gap**:`obs_mask` 未知 category silent skip — follow-up
  加 validation。
