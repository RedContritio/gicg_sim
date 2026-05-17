---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: opponent-mix
---

# Opponent Mix — registry + mix sampling + baseline 接口

> 本 subtopic 锚定 OpponentRegistry(actor + eval 共用)、mix sampling
> 与 baseline 接口的 paradigm-agnostic 形态。详细 BaselineSpec dataclass
> 字段 / historical ckpt 加载 / mix sampling 权重协议在 P2
> `unified-training-pipeline` change 落地。

## 1. Scope

本 subtopic 覆盖:

- OpponentRegistry — actor 与 eval 共用的注册表
- Mix sampling — weighted choice over registered opponents
- BaselineSpec 接口 — fixed("F1-D2") / pool_sample() / historical ckpt
- Historical opponent — checkpoint snapshot 加载与 LocalNetworkProvider
  使用

不覆盖:

- 具体 baseline 实现(F1-Dn MCTS / mcts_pure / random)—
  `training/core/baselines/` 实现层细节
- 各 paradigm 选用哪些 opponent — 各 paradigm dossier(默认 mix 配置)
- Historical pool 构造策略(PPO ELO 时代废除,详 `memory
  project_pool_elo_design`)— 仅保留接口可重现 historical ckpt 加载

## 2. 总体形态

```
OpponentRegistry
    register("random", lambda: RandomBaseline())
    register("F1-D2",  lambda: F1MCTSBaseline(depth=2))
    register("mcts_pure", lambda: MCTSPureBaseline(...))
    register("hist_<ckpt-id>", lambda: HistoricalCkptBaseline(...))

OpponentMix(cfg)
    weights:  {"random": 0.1, "F1-D2": 0.6, "hist_*": 0.3}
    sample() → Opponent instance(thread-safe;may be cached)
```

## 3. Core SHALL invariants

**核心 SHALL**:

1. OpponentRegistry SHALL be paradigm-agnostic 位于
   `training/core/opponents/registry.py`(P2 落地)— actor 与 eval
   worker 共用同一 registry 实例(或同一注册函数集)。

2. BaselineSpec 接口 SHALL be paradigm-decoupled — `BaselineSpec.fixed
   ("F1-D2")` / `BaselineSpec.pool_sample(weights)` 等返回对象不携带
   paradigm 字段,EpisodeRunner 通过 EpisodePolicy 抽象屏蔽差异。

3. Historical opponent SHALL load weights via LocalNetworkProvider —
   `HistoricalCkptBaseline(ckpt_path, paradigm)` 内部用对应 paradigm 的
   `make_network` + load_state_dict,EpisodePolicy 同 train actor 同类。

4. Mix sampling SHALL be weighted choice — cfg 提供
   `{name: weight}` mapping,sample 时按 weight normalize 后抽取。同一
   episode 内 opp SHALL not change(避免 mid-episode swap)。

5. New opponent type SHALL register via single function call —
   `register_opponent(name, factory)` 是唯一新增 baseline 入口;不允许
   paradigm-specific opp 类型在 actor / eval 处分别注册(避免双侧不
   一致)。

6. OpponentRegistry SHALL support deterministic resolution given
   scenario_seed — `OpponentMix.sample(rng_seed)` 行为可复现,便于
   eval 跨 run 对齐。

## 4. BaselineSpec 接口

BaselineSpec 是 cfg 层抽象,paradigm-agnostic 字段:

骨架(P2 定 dataclass):

- `BaselineSpec.fixed(name)` — 单 opp,所有 episode 用同一
- `BaselineSpec.pool_sample(weights)` — 按权重 sample mix
- `BaselineSpec.historical(ckpt_path)` — 单 ckpt as opp
- `BaselineSpec.mix_with_historical(weights, ckpt_pool)` — mix + 历史
  ckpt 池(P2 后视需求 ship)

**SHALL**:

1. BaselineSpec SHALL be cfg-serializable(JSON / TOML round-trip)—
   eval scenario / actor mix 都通过 cfg 表达。

2. BaselineSpec SHALL be resolved at runtime via OpponentRegistry —
   `spec.resolve(registry) -> Opponent` 返回 EpisodeRunner 可消费对象。

3. BaselineSpec 字段 SHALL NOT 携带 paradigm-specific 参数(MCTS depth
   / temperature 等由 baseline factory 自身处理)。

## 5. Mix sampling 协议

Mix sampling 用于 actor 训练时 opp 的 stochastic 抽取(diversity 来
源)与 eval scenario 的 weighted 评估。

**SHALL**:

1. Mix weights SHALL sum to 1 after normalization;cfg 可填整数比例,
   resolver 自动 normalize。

2. Actor mix sampling SHALL use scenario-specific RNG(派生自
   `meta.seed` + episode_index)— 不同 actor 进程间确定性可复现。

3. Eval mix sampling SHALL be deterministic given scenario_seed —
   EpisodeSpec 中 scenario_seed 决定 opp 抽取,swap-sides 不重抽
   opp(swap 仅交换先后手)。

4. Mix sampling SHALL cache resolved Opponent instances when possible
   — 重型 baseline(historical ckpt 加载 network)不应每 episode
   重新加载。

## 6. Historical opponent

Historical ckpt as opp 是 self-play 训练的可选机制(AZ pool / PPO ELO
等历史用法)。当前 AZ D4 后弃对手池,但接口保留以便 P2 后视实测复活。

**SHALL**:

1. Historical opp SHALL load via `BaselineSpec.historical(ckpt_path)`
   — ckpt 内含 `meta.paradigm` 字段(详 SHALL 12 in 主 spec),resolver
   按字段路由到对应 paradigm 的 `make_network`。

2. Historical opp SHALL run in LocalNetworkProvider only(不通过
   Remote inference server,避免与 train inference 资源竞争)— 每
   EvalWorker / Actor 自行 load + forward。

3. Historical opp 加载 SHALL be lazy + cached — registry 持有 lazy
   factory,首次 sample 时加载,同进程内 cache 复用。

## 7. Cross-references

- EpisodePolicy / NetworkProvider 协议详 [`./protocols.md`](./protocols.md)
- EvalWorker 使用 OpponentRegistry 详 [`./eval.md`](./eval.md)
- Pipeline state 不持有 opponent 实例(per-process cache)详
  [`./pipeline.md`](./pipeline.md)
- Pool ELO 历史(AZ D4 后弃)→ `memory project_pool_elo_design` +
  `memory project_pool_elo_followups`(已 OBSOLETE)
- AZ D4 决策与 arena/gauntlet 替代 → `memory project_az_stage0_3_baselines`
- F1-D2 baseline 强度参考 → `memory project_greedy_baseline` +
  `memory feedback_stage0_f1d2_judge`
- 详细 BaselineSpec dataclass 字段 + historical ckpt 加载实现在 P2
  `unified-training-pipeline` change `design.md` 落地
