---
last_updated: 2026-06-12
status: LIVE
schema_version: 0
capability: env-config
---

# Env Config — gicg_env Python RL 环境层规约

> 本 capability spec 治理 `gicg_env/` 目录下的 Python RL 环境层 —
> `GicgEnv` 类(`gicg_env/env.py`)、obs encoding(`env_obs.py`)、
> action encoding(`env_action.py` + `env_query.py`)、reward shaping
> (`env_reward.py`)、env lifecycle(reset / step / done / clone)。
> 本 spec 仅治理 **paradigm-agnostic** 接口契约;paradigm-specific 行
> 为(AZ pure terminal / DMC dense shaping / PPO advantage 等)由各
> paradigm dossier 承接。
>
> 本 spec 从 `docs/1_specs/env/README.md`(原标 "WIP")reverse engineer
> 写成 SHALL 形式,源 truth 是 `gicg_env/` 当前 shipped 代码 + 多个
> ADR(0011 pool versioning / 0019 typed obs)。

## 1. Purpose

`gicg_env` 是 Python 训练栈与 Go 引擎之间唯一桥梁。需被规约化,否则会出现:

- env 接口随 paradigm 演化漂移 — AZ / DMC / PPO 各自加 hook,接口边
  界(哪些 SHALL paradigm-agnostic、哪些 paradigm-specific)模糊
- obs / action / reward 编码与下游网络消费契约脱节(已发生:ADR-0019
  typed obs 落地时 env_obs.py 与网络 embedders 字段约定二次确认)
- Scenario injection(`pool` / `deck_padding` / `decks` / `fix_dice` /
  `obs_mask`)分散在 env / cfg / matchup 三层,无统一 spec
- IS-MCTS determinization(`set_player_dice` / `set_player_hand` /
  `set_player_deck`)等 hidden-state injection 入口未规约,被搜索代
  码假定存在又随时被搬移

本 spec 提供 4 大类约束:

- **Observation schema**(详 [`./obs.md`](./obs.md))
- **Action encoding + legal mask**(详 [`./action.md`](./action.md))
- **Reward signal**(详 [`./reward.md`](./reward.md))
- **Lifecycle + scenario injection**(详 [`./lifecycle.md`](./lifecycle.md))

## 2. Scope

**In scope**:

- `GicgEnv` 公共方法签名(`__init__` / `reset` / `step` / `clone` /
  `close` / `snapshot` / `restore`)
- Static + Dynamic obs 数据流(`get_static_obs()` / `get_dynamic_obs()`
  → Python 端 normalize → 网络消费)
- Action enumeration + legal mask + dice payment(`get_legal_actions` /
  `get_legal_action_payments` / `get_action_refs`)
- Reward terminal signal(`info['z']`)与可选 dense shaping
  (`RewardShaping`)的 paradigm-agnostic 接口
- Scenario cfg 字段(`team_0` / `team_1` / `card_pool` / `pool` /
  `deck_padding` / `decks` / `fix_dice` / `obs_mask` / `max_rounds`)
- IS-MCTS determinization injection(`set_player_dice` /
  `set_player_hand` / `set_player_deck` / snapshot / restore)
- Mirror-match disjoint teams(ADR-0011 `disjoint_teams=True`)交互

**Out of scope**:

- ctypes 层 / C API surface — 由 [`engine-capi`](../engine-capi/spec.md)
  治理(本 spec 的 `gicg_env/engine.py` 是该 capability 的 Python 端
  消费者)
- Counter / hook 引擎内部布局 — [`engine-dsl`](../engine-dsl/spec.md)
- Action enum 数值 / 引擎侧 ActionKind 定义 — [`engine-actions`](../engine-actions/spec.md)
- Obs schema 在网络侧消费(encoder 形状对齐) — [`network-architecture/obs`](../network-architecture/obs.md)
- Paradigm-specific reward shaping 公式与系数 — 各 paradigm dossier
  (e.g. AZ D5 决策 / PPO 1.0 vs 1.1 asymmetric / DMC stage-coef)
- Eval / gauntlet 协议 — [`eval-protocol`](../eval-protocol/spec.md)

## 3. Core SHALL invariants

以下 11 条 invariant 是本 capability 的硬约束。任意冲突应作为
OpenSpec change 提案修订,而非在代码中静默偏离。

1. **Canonical Python env**:`gicg_env.GicgEnv`(`gicg_env/env.py`)
   SHALL be the canonical Python RL env class。`tools/` / `training/`
   下其他 env wrapper SHALL be thin adapters,SHALL NOT 平行实现
   reset / step。

2. **Engine binding via ctypes**:Env SHALL connect to `libgicg.dylib`
   / `.so` / `.dll` via `gicg_env/engine.py` ctypes wrapper,SHALL NOT
   embed cgo or alternative bindings。详 [`engine-capi`](../engine-capi/spec.md)。

3. **`reset(seed)` returns initial obs**:`reset(seed, deck_seeds=None)`
   SHALL re-roll a fresh game(no DSL reload)+ return the initial
   dynamic obs。`deck_seeds=(p0, p1)` 可选 3-axis seed split。详
   [`./lifecycle.md`](./lifecycle.md)。

4. **`step(action_idx)` 4-tuple**:`step()` SHALL return
   `(obs, reward, done, info)` 4-tuple。`obs` 为 float32 numpy array
   (or zeros on terminal),`reward` 为 perspective-of-actor scalar,
   `done` 为 bool,`info` 至少含 `winner` + `turn`,terminal 步额外含
   `z` ∈ {-1, 0, +1}(P0 perspective)。详 [`./lifecycle.md`](./lifecycle.md)。

5. **Obs typed schema**:Obs SHALL follow ADR-0019 typed schema —
   `meta` + `counter_values` + `card_buckets` + `enemy_sizes` +
   typed segments(`recent_damage` + `prepare_skill` + `modifier_log`)。
   Counter values 在 Python 端做 per-slot (min, max) normalize;typed
   segments **不** normalize(网络侧 embedders 自行 cast)。详
   [`./obs.md`](./obs.md)。

6. **Legal mask paradigm-agnostic**:`get_legal_actions()` SHALL return
   `(kinds, dice_payments)` tuple,顺序 stable across 同一 state。
   `get_legal_mask(max_actions)` SHALL return bool ndarray with
   `mask[:n_legal] = True`。Mask 形式不绑 paradigm(AZ MCTS / CFR
   regret / PPO logits 共用)。详 [`./action.md`](./action.md)。

7. **Reward terminal signal**:`reward_shaping=None` 时 `step()` 返
   `reward=0.0`,paradigm 通过 `info['z']` 读 P0-perspective ±1 / 0。
   `reward_shaping=RewardShaping(...)` 时 `step()` 返 per-step
   shaping(Δ RewardEvents × coefs + optional terminal bonus),从
   acting player 视角。详 [`./reward.md`](./reward.md)。

8. **Strict terminal guard**:`info['z']` SHALL only be present on
   terminal step(`done=True`)。Engine `winner == -1`(未终局)被传
   入 `_terminal_z` SHALL raise `ValueError`,而非静默返 0(已修
   bug)。详 [`./reward.md`](./reward.md)。

9. **Scenario injection cfg-driven**:`__init__` SHALL accept
   `team_0` / `team_1`(必需)+ optional `card_pool` / `pool` /
   `deck_padding` / `decks` / `fix_dice` / `max_rounds` / `obs_mask` /
   `obs_config` / `reward_shaping` / `seed` / `data_dir` / `lib_path`。
   不接受未声明 kwarg。详 [`./lifecycle.md`](./lifecycle.md)。

10. **ADR-0011 pool spec + F4 explicit decks**:Env SHALL respect
    ADR-0011 pool versioning via `pool` cfg 字段(单 str 或
    list[str]),deck filler 由 `deck_padding={"card": str,
    "target_size": int}` 控制,per-player 显式 deck 由
    `decks=[deck_p0, deck_p1]` 声明(F4)。无显式 deck 且 eligible >
    target_size SHALL fail game creation — 引擎 SHALL NOT 静默截断。
    `pool=None` 时引擎 default `["v_legacy"]`。详
    [`./lifecycle.md`](./lifecycle.md)。

11. **IS-MCTS determinization injection**:Env SHALL expose
    `snapshot()` / `restore(snap_id)` / `snapshot_free(snap_id)` +
    `set_player_dice` / `set_player_hand` / `set_player_deck` +
    `log_suspend` / `log_resume` 入口,paradigm-agnostic。MCTS /
    search 代码 SHALL 用这些方法,SHALL NOT 直接访问
    `env._engine.*`。详 [`./action.md`](./action.md)。

## 4. Subtopics

本 capability 由本文件 + 4 个 subtopic 组成。每个 subtopic 专注一组
正交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [Obs schema](./obs.md) — Static / Dynamic obs 字段、layout、Python
  端 normalize 规则、partial-observability mask(`obs_mask`)、ADR-0019
  typed segments
- [Action encoding](./action.md) — Legal actions / dice payments /
  action refs / action labels / legal mask、IS-MCTS injection 入口
  (snapshot / restore / set_player_*)、`step_target` 路由
- [Reward signal](./reward.md) — Paradigm-agnostic terminal `info['z']`
  契约 + 可选 `RewardShaping` dense delta、strict terminal guard、
  perspective-of-actor 约定
- [Lifecycle + scenario](./lifecycle.md) — `__init__` cfg 字段、
  `reset` / `step` / `clone` / `close` 生命周期、pool / deck_padding /
  decks / fix_dice / obs_mask / max_rounds 注入、context manager

## 5. Cross-references

**Sibling capability specs**:

- [`engine-capi`](../engine-capi/spec.md) — libgicg / ctypes 接口
  契约。本 spec 的 `gicg_env/engine.py` ctypes wrapper 是其 Python 端
  消费者。
- [`engine-actions`](../engine-actions/spec.md) — ActionKind enum 与
  引擎侧 legal-actions 枚举语义。本 spec 仅治理 Python 端 mask /
  refs / payments 暴露。
- [`engine-runtime`](../engine-runtime/spec.md) — DSL 加载 / sandbox /
  game lifecycle 引擎侧。
- [`network-architecture/obs`](../network-architecture/obs.md) — 网
  络侧 obs schema 消费契约,本 spec obs.md 与之 1:1 对齐。
- [`eval-protocol`](../eval-protocol/spec.md) — eval / gauntlet 协
  议,通过 `GicgEnv` 实例化 + matchup runner 消费。
- [`openspec-policy`](../openspec-policy/spec.md) — 本 spec 格式 /
  阈值。

**Active OpenSpec archive**(cross-cutting):

- [`changes/archive/0011-pool-versioning`](../../changes/archive/0011-pool-versioning/) —
  pool / deck_padding / disjoint_teams cfg 字段引入(本 spec SHALL 10)
- [`changes/archive/0019-dsl-v6-semantic-engine`](../../changes/archive/0019-dsl-v6-semantic-engine/) —
  Typed obs schema(recent_damage / prepare_skill / modifier_log)
  落地(本 spec obs.md 详细 cross-ref)

**History / source**:

- `docs/1_specs/env/README.md`(原 placeholder,本 spec 落地后更新
  为 link)
- `docs/5_history/audits/env_audit.md` — 历史 env 审计

**Memory cross-references**:

- 训练完必跑 gauntlet → `memory feedback_post_run_gauntlet`
- Pool versioning ADR-0011 详 → `memory project_pool_versioning`
- Typed obs ckpt 全失效 → `memory project_typed_obs_ckpt_break`

## 6. Status

- **Created**:2026-05-15(P1-T6)
- **Version**:0(初始落地)
- **Source**:`gicg_env/env.py` + `env_obs.py` + `env_action.py` +
  `env_reward.py` + `env_query.py` shipped code
- **Expected revision triggers**:
  - ADR-0019 §B.3 后续 phase 加新 typed segment(本 spec obs.md 同步
    扩展)
  - Cfg 字段扩展(新 scenario knob)→ lifecycle.md
  - 新 paradigm 接入引入新 RewardShaping coef → reward.md
  - IS-MCTS 之外的 search 方案(若 D4 重开)→ action.md
