---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: obs
---

# Observation Schema — Static / Dynamic / Per-decision

> 当前契约补充（2026-09-12）：v8 counter 使用 canonical 身份布局，meta[18]
> 标明 observer；数值归一化与私有信息遮罩在 Python 环境层处理，网络结构化读出
> 按 observer 转换。参见 [v8 设计](../../changes/nn-perspective-v8/design.md)。
> v9 在统一 16 字段实体区增加执行帧 kind=5、规则绑定 kind=6。
> 卡牌选目标可显示程序入口及可见参数，嵌套伤害仍标记为不完整的重放路径。
> 字段与可见性约束见 [v9 设计](../../changes/nn-target-frame-v9/design.md)。
> 下文早期 shape/全相对视角描述未完整迁移，冲突时以上当前契约优先。

> 本 subtopic 锚定 GICG 主网络的输入数据契约。Obs 分三层 — **static**
> (per-game,一次 compute,~221 KB)/ **dynamic**(per-step,每决策
> compute,~8 KB)/ **per-decision**(action_refs / action_payments,
> 绑 legal_actions)。视角(perspective-specific)在 engine 层已处理,
> network 端不再 mask。
>
> 本文档治理 obs schema 的字段名、shape、语义,SHALL 化约束。具体的
> 网络消费(encoder 形状对齐、mask 来源)详 [`./encoders.md`](./encoders.md)。

## Semantic rule graph supplement (2026-09-14)

`get_rule_graph()` SHALL return graph schema version 2. In addition to
`counter_owners`, `counter_links` and `card_links`, it exposes `skill_links` and `card_hook_links`:
rows `(canonical_skill_active_hook, referencing_active_hook)` in the current
observation layout (`card_hook_links` uses canonical card hooks). No raw skill IDs, names, hidden state or calculated damage
results are exported. Empty edge arrays SHALL retain their two-column schema
when batched; missing version/fields SHALL NOT silently use legacy observations.

Edges describe conservative static definition-reference incidence, not whether
a callback will execute. The interpreter collects typed `SkillRef` and
`LazySkillRef` lexical references, including local aliases and captured helper
closures, without executing rule expressions or reading live counters. Ordinary
integers SHALL NOT be inferred as skill IDs. References to an owner's own skill
bind that canonical actor instance; foreign/shared definitions retain all
matching instances when the actor cannot be proven statically. Dynamic runtime
selection remains in DSL/execution state and is not converted into a static
trigger predicate. A same-file relationship alone SHALL NOT create skill edges.

Canonical observation nodes SHALL expose definition kind using opcode 15;
arbitrary card/skill IDs SHALL NOT masquerade as `OpLoadImm` literals.
All ActorCritic paradigms and CFR SHALL aggregate referenced hook features into
canonical skill and card features before action embedding. SemanticQNet SHALL
reuse that same relation module and aggregate exactly once. BC and RL
observations SHALL preserve these edges through collection, replay collation,
batch training and every inference provider. Layout permutation must preserve
physical relations. Graph/encoder changes require fresh compatible weights and
experience; old artifacts must not be relabelled to bypass compatibility checks.

## 1. Scope

本 subtopic 覆盖:

- Static obs(`GameGetStaticObs` 输出)的 5 个字段及 shape
- Dynamic obs(`GameGetDynamicObs(player_perspective)` 输出)的 4 个
  字段及 shape
- Per-decision action features(`action_refs` + `action_payments`)的
  shape 与 kind enum
- 视角(perspective)约定 — engine 在 dynamic obs 层面已处理

## 2. Static obs

### 2.1 SHALL invariants

1. Static obs SHALL be a flat int array from `GameGetStaticObs()`,
   Python 端按字段切分,SHALL be computed **exactly once per game**
   (game_start 时由 inference server cache)。

2. Static obs SHALL contain these fields:
   - `counter_meta`:`(n_counter_slots, 3)` — `[min, max, shuffled_sid]`
   - `char_skill_refs`:`(2, ObsMaxChars, ObsMaxSkillsPerChar)`
   - `hook_ir`:`(n_hooks, max_ops_per_hook, fields_per_op)`
   - `char_elements`:`(2, ObsMaxChars)`
   - `definition_links` fixed-capacity trailer: schema version and count followed by
     `(canonical_active_hook, effect_active_hook)` pairs

3. `n_counter_slots`、`n_hooks`、`max_ops_per_hook`、`ObsMaxChars`、
   `ObsMaxSkillsPerChar` SHALL be read from engine at network construction
   time(via `GameGetStaticObsSize()` / 相关查询),SHALL NOT be
   hardcoded in network init。

4. The definition-link trailer SHALL have capacity 16384 and SHALL be present
   even when its count is zero. Engine overflow, Go/Python capacity drift,
   malformed indices and legacy observations without this trailer SHALL fail
   loudly. Its indices are positions in the shuffled active-hook layout, so
   per-game hook shuffling remaps both endpoints together.

### 2.2 `counter_meta` 字段语义

- shape `(n_counter_slots=1832, 3)`,列分配:
  - 列 0:`min` — counter 下限(静态,per-game 不变)
  - 列 1:`max` — counter 上限(静态)
  - 列 2:`shuffled_sid` — per-game shuffled stable ID
    (agent 看不到稳定槽位语义,反 ID)
- 衍生 `active_slot_mask = (min ≠ 0 or max ≠ 0)` — 该 slot 是否承载
  真实 counter,详 [`./encoders.md`](./encoders.md) CounterEncoder。

### 2.3 `char_skill_refs` 字段语义

- shape `(2, ObsMaxChars=6, ObsMaxSkillsPerChar=10)` —
  per-player × per-char-slot × per-skill-slot 索引
- 每 `(p, c, s)` 存该槽位第 `s` 个技能的 canonical `on_skill_use`
  hook 在 active hook 列表中的位置,或 `-1` 表示空 slot
- 位置 `(p, c)` 结构性编码 owner;物理 slot `s` 通过 `SkillSlotPerm[p][c]`
  每 `(p, c)` 独立 Fisher-Yates 洗(anti-position-ID,类比 per-char
  counter sid 洗)
- Gather 目标 = pointer-net 策略头给 SKILL 动作用的同一个 canonical
  hook embedding — 动作选择和观测侧表示对齐

### 2.4 `hook_ir` 字段语义

- shape `(n_hooks=900, max_ops_per_hook=128, fields_per_op=5)`
- 每 hook 是 padded IR op 序列；每个 op 为 `(opcode, dst, op1, op2, op3)`。
- HookEncoder SHALL consume IR ops and the active-hook mask with grad
  (训练路径每次 forward 重跑 hook_encoder),详
  [`./encoders.md`](./encoders.md)。

### 2.5 `definition_links` 字段语义

- Trailer shape is `2 + 2 * 16384`: the first scalars are schema version
  and edge count; remaining storage contains row-major endpoint pairs and
  zero padding.
- The engine combines `skill_links` and `card_hook_links`, sorts and deduplicates
  the pairs, and panics rather than truncating on overflow.
- Python converts an empty graph to one `(-1, -1)` padding row for batching.
  Valid endpoints SHALL be non-negative and within the active hook layout.

## 3. Dynamic obs

### 3.1 SHALL invariants

1. Dynamic obs SHALL be queried per decision via
   `GameGetDynamicObs(player_perspective)`,SHALL be
   **perspective-specific**(己方在前,对方在后;engine 已处理)。

2. Dynamic obs SHALL contain at minimum these four fields:
   - `meta`:`(18,)` — phase、round、is_my_turn、双方结束声明、相对先结束方、回合上限、待选类型/强制标志、固定骰模式与8色配置；详见 [v5 观测契约](../../changes/effect-audit-v5/observability.md)
   - `counter_values`:`(n_counter_slots=1832,)`
   - `card_buckets`:`(4, n_card_slots=80)` — own hand / own deck /
     own discard / enemy discard
   - `enemy_sizes`:`(2,)` — 对手手牌数、牌堆数(public info)

3. Network SHALL NOT mask perspective in Python — engine layer
   `BuildDynamicObs` already enforces:
   - 己方:手牌内容 / 牌库内容 / 弃牌堆内容 / 角色 counter
   - 对方:仅弃牌堆内容(public)+ 仅手牌数 / 牌库数(via
     `enemy_sizes`)+ 角色 counter

### 3.2 字段 cross-ref

- `counter_values` 配 `counter_meta` 列 2(shuffled_sid)+
  `active_slot_mask` 衍生 — CounterEncoder 消费
- `card_buckets` 配 CardEncoder 的 `(n_buckets=4, n_card_slots=80)`
  table 消费
- `enemy_sizes` 作为残差直接加到 CardEncoder pool 输出
- `meta` 经 `meta_proj` 投影后作为 global_state 的一路

## 4. Per-decision features

### 4.1 SHALL invariants

1. Per-decision input SHALL provide two arrays bound to the current
   legal-actions list:
   - `action_refs`:`(max_actions=2048, 3)` — 每行 `[kind, hook_idx, char_idx]`
   - `action_payments`:`(max_actions=2048, 8)` — 8 维骰子支付组合
     `[omni, fire, ice, water, electro, geo, grass, slot7]`

2. `kind` SHALL be one of `SKILL=0` / `CARD=1` / `SWITCH=2` /
   `END_TURN=3`。非合法位 `kind=END_TURN` 占位 + mask 置 false。

3. Per-decision shapes SHALL be padded to `max_actions=2048` —
   `legal_mask` 由 caller 提供,policy head SHALL apply mask before
   softmax(详 [`./loss.md`](./loss.md) 与 [`./heads.md`](./heads.md))。

### 4.2 `action_refs` 列语义

- 列 0(`kind`):动作类型 enum
- 列 1(`hook_idx`):对 SKILL/CARD 指该动作的典型 hook 在 active
  hook 列表中的位置(e.g. `on_skill_use` 的 hook 位);其他 kind 为
  `-1`
- 列 2(`char_idx`):对 SWITCH 指目标角色槽位;其他 kind 为 `-1`

### 4.3 `action_payments` 列语义

- 列 0-7 对应 8 种骰子(omni / 7 elements / 第 8 slot 兜底)的
  本次支付数量
- MVP(AP 作为万能骰子)阶段 `action_payments` 始终为零或极简 —
  `dice_combo_proj` 退化为约零残差。真实骰子系统上线时
  `dice_combo_proj` 才显著影响 policy head logit

## 5. Cross-reference

- **Encoder consumption**:[`./encoders.md`](./encoders.md) —
  HookEncoder / CounterEncoder / CardEncoder 如何消费上述字段
- **Head consumption**:[`./heads.md`](./heads.md) — Policy head 如何
  用 `action_refs` 三路 gather + dice_combo 残差;Value/Delta head
  消费 global_state(由 obs + encoder pipe 生成)
- **Engine source**:`gicg_engine/observation.go` —
  `BuildStaticObs` / `BuildDynamicObs` 实现;字段 shape 与本 spec
  对齐
- **DSL v6 typed obs**:
  `openspec/changes/archive/0019-dsl-v6-semantic-engine/` — typed
  damage encoder / semantic engine 升级路径;本 spec obs schema 在
  ADR-0019 全量 ship 后会改写为引用 dsl-v6 schema(P1-T2 阶段仍
  锚 C1v7 整数 obs)
