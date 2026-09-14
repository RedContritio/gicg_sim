---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: eval-protocol
subtopic: baselines
---

# Baselines — random / F1-Dn / mcts_pure / historical ckpt 接口

> 本 subtopic 锚定 gauntlet baseline player 接口契约 —
> `training/core/matchup/loaders.py::LOADERS` registry 提供 universal
> player（random / mcts_pure / greedy）和按需加载的 paradigm player，
> 并承接 historical ckpt。
>
> 源 truth:`training/core/matchup/loaders.py` + `players.py`
> (MCTSPlayer)+ `greedy_player.py` + `greedy_scorers.py` +
> `greedy_dice.py`。

## 1. Scope

本 subtopic 覆盖:

- `LOADERS` registry pattern + `load_player(spec) -> PlayerBuilder`
- `_PlayerProtocol` 接口:`select_action(env) -> int`
- universal player type random / mcts_pure / greedy，以及按需加载的
  paradigm player（az / bc / cfr / dmc / ppo；部分组合会明确拒绝）
- Greedy 三轴变体:Features(F1..F5)× Depth(D1..D3)× dice_greedy bool
- Historical ckpt 接入 pattern(via `az` / `cfr` type + ckpt path)
- `PlayerBuilder` callable signature `seed -> _PlayerProtocol`

不覆盖:

- 具体 F1..F5 feature 公式 — 见 `training/core/matchup/greedy_player.py`
  module docstring + `greedy_scorers.py`(spec 引用 docstring 而非 inline
  复制公式)
- AZ MCTS PUCT 超参 — AZ paradigm dossier(`training/paradigms/az/mcts/config.py::MCTSConfig`)
- CFR strategy net 训练 — CFR paradigm dossier
- 未来 Go gauntlet baselines(`gicg_baselines/` capability) — 单独
  spec

## 2. `LOADERS` registry

### 2.1 Pattern

```python
PlayerBuilder = Callable[[int], _PlayerProtocol]
# Each loader: spec dict -> PlayerBuilder (capture ckpt-load + cfg)
# Builder: seed (int) -> _PlayerProtocol instance with RNG seeded

register_loader('random', _loader_random)
register_loader('mcts_pure', _loader_mcts_pure)
register_loader('greedy', _loader_greedy)

# az / bc / cfr / dmc / ppo loaders live in
# training/paradigms/<name>/_player_loader.py and self-register on
# the first lookup through the lazy LOADERS mapping.
```

### 2.2 SHALL invariants

1. `load_player(spec)` SHALL look up `spec['type']` in `LOADERS`,
   `raise ValueError` if `type` missing or unknown(list known)。

2. Loader return SHALL be `PlayerBuilder = Callable[[int], _PlayerProtocol]`
   — `spec` 在 loader 调用时 freeze(ckpt load / cfg parse 一次性),
   builder 接受 per-game seed 后返回 stateful player instance。

3. `_PlayerProtocol.select_action(env: GicgEnv) -> int` SHALL be
   the only method consumed by `_play_one` — player 内部 RNG / agent
   wrap / search 配置都 hidden in player instance。

4. New baseline type SHALL be added by registering in `LOADERS`,
   SHALL NOT bypass via inline dispatch in matchup.py。

## 3. `az` / `cfr` — trained network players

### 3.1 `az` loader

```
_loader_az(spec):
    agent = _load_agent_from_ckpt(spec['ckpt'])   # AZ Agent + cfg
    n_sims = int(spec.get('n_simulations', 0))
    max_depth = int(spec.get('max_rollout_depth', 400))

    def builder(seed):
        if n_sims == 0:  return _AZGreedyPlayer(agent)              # argmax
        else:            return _AgentMCTSPlayer(agent, n_sims, seed, max_depth)
    return builder
```

### 3.2 `cfr` loader

```
_loader_cfr(spec):
    Mirror of _loader_az but loads CFRStrategyNet via CFRAgent.
    Same builder dispatch — argmax (n_sims=0) vs _AgentMCTSPlayer.
```

### 3.3 SHALL invariants

1. Ckpt blob SHALL be torch.load with `weights_only=True` +
   `map_location='cpu'`(SHALL NOT eval-side GPU,inference isolation
   per `training-architecture/eval`)。

2. Blob SHALL contain `'cfg'` + `'net'` keys;缺一 SHALL
   `raise RuntimeError`(SHALL NOT silent default cfg)。

3. Agent SHALL `agent.net.eval()` 在 build 时 — gauntlet 不训练。

4. `n_simulations == 0`(argmax)SHALL use `_AZGreedyPlayer`
   wrapper(no MCTS,直接 `eval_state` argmax)。

5. `n_simulations > 0` SHALL use `_AgentMCTSPlayer` 包 MCTS with
   `MCTSConfig(dirichlet_eps=0.0, temperature_switch_step=0,
   value_mix_lambda=1.0, prior_mix_lambda=1.0, lambda_anneal_games=0,
   discovery_checkpoints=())` — eval-time MCTS 无 exploration noise,
   全 exploit。

6. `_AgentMCTSPlayer.select_action` SHALL `log_suspend()` / `log_resume()`
   bracket — MCTS rollout 事件不污染 replay log。

### 3.4 Historical ckpt

Historical opponent ckpt 接入 SHALL 走同一 `az` / `cfr` type,只换
`ckpt` path — service 端无 historical-specific type(简化)。Service
端 SHALL pre-check ckpt 文件存在(`validate_request` runtime check)。

## 4. `random` — uniform legal

### 4.1 Implementation

```
class _RandomPlayer:
    def __init__(self, seed):
        self.rng = random.Random(seed)
    def select_action(self, env):
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            raise RuntimeError('RandomPlayer: env has no legal actions')
        return self.rng.randrange(len(kinds))
```

### 4.2 SHALL invariants

1. `_RandomPlayer.select_action` SHALL sample uniform over current
   legal action count(含 dice payment fanout — 不 collapse)。

2. `n_legal == 0` SHALL `raise RuntimeError` — defensive(同 arena /
   gauntlet)。

3. Seed SHALL be per-game(builder receives seed),保证 reproducibility。

## 5. `mcts_pure` — pure UCT, no network

### 5.1 Implementation

`MCTSPlayer` in `training/core/matchup/players.py` — UCT with
uniform priors and random rollouts。

### 5.2 SHALL invariants

1. `n_simulations` SHALL be required `>= 1`(schema enforced;loader
   re-checks)— no network prior to fall back on at budget 0。

2. Default `max_rollout_depth=80` + `c_puct=1.4`(`DEFAULT_C_PUCT`)。

3. `select_action` SHALL bracket with `log_suspend` /
   `log_resume`(同 AZ MCTS)。

4. MCTS SHALL use `env.snapshot()` / `restore()` / `snapshot_free()`
   for tree descent — 与 [`env-config/action`](../env-config/action.md)
   §4-§5 一致。

5. Random rollouts(`_random_rollout`)SHALL play random legal actions
   until done or `max_depth` reached;truncated rollouts return
   `env._engine.winner`(可能 -1)— `_p0_value` 把 -1 / 2 一律视
   为 draw value 0.5。

## 6. `greedy` — F1-F5 × D1-D3 × dice_greedy

### 6.1 Three orthogonal axes

- **Features**(F1..F5):什么打分函数 — F1 minimal HP delta /
  F2 +kill / F3 +heal / F4 +shield+reaction / F5 +energy_overflow+ap_waste。详
  `greedy_player.py` + `greedy_scorers.py` module docstring。
- **Depth**(D1..D3):lookahead plies — D1 NPC(我方 argmax,opponent
  unmodeled)/ D2 adversarial 2-ply minimax / D3 self-3-ply。
- **dice_greedy**(bool):是否 collapse dice payment fanout via 手
  工 heuristic(active-color > backline > omni > abundant junk > rare junk;
  min total value)。降低 per-decision legal-action 数 5-30×。

### 6.2 SHALL invariants

1. Feature 选择 SHALL ∈ {`F1`, `F2`, `F3`, `F4`, `F5`}(schema
   enum 强制)+ depth ∈ {1, 2, 3}。组合空间 5 × 3 × 2 = 30 种。

2. F1/F2 SHALL only read `env.export_view()` HP + alive_count 差;
   F3/F4/F5 SHALL 额外读 `env.reward_events(player)` accumulator(经
   query helper)。SHALL NOT 互窜 — scorer signature 统一
   `(view_before, view_after, events_before, events_after, me)` 但
   F1/F2 忽略后两个。

3. Depth ≥ 2 SHALL simulate opponent's best response via the **same**
   feature function(对手与我方 reward 对称 — D2 是 minimax,D3 是
   3-ply self-look)。SHALL NOT 用 different scorer for opponent。

4. `dice_greedy=True` SHALL preserve final-choice quality with strict
   `n → n_logical` 速度 trade — heuristic 选 payment 后,后续逻辑仍
   按选定 payment 跑。SHALL NOT 改变 logical action 排序。

5. F3-F5 字段细节:scorer SHALL access REWARD_EVENTS_FIELDS by
   indexed constants(SHALL NOT hard-code int — 与 `env_reward.py`
   `_IDX` convention 一致)。

### 6.3 Stable baseline ladder

Gauntlet 用 F1-D2 作为 production baseline；历史 AZ stage 0-3 结果见
`docs/5_history/`。Greedy 强度 monotone 假设:F1 < F2 < ... + D1
< D2 < D3。Anomaly("F1 > F5" / "D3 < D1")出现时 SHALL 当 bug
诊断,非 silent 接受。

## 7. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 6 — baselines 锚点
- [`./service.md`](./service.md) §3.4 — schema `player_spec` oneOf
- [`./gauntlet.md`](./gauntlet.md) — `_play_cell` 内 builder 调用
- [`env-config/action`](../env-config/action.md) — `snapshot` /
  `restore` / `set_player_*` IS-MCTS injection
- [`network-architecture`](../network-architecture/spec.md) —
  `_AZGreedyPlayer` / `_AgentMCTSPlayer` consumes `agent.eval_state`
- [`docs/5_history/ablations/stage3_ppo_closure.md`](../../../docs/5_history/ablations/stage3_ppo_closure.md)
  — historical strength evidence

## 8. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`training/core/matchup/loaders.py` +
  `players.py` + `greedy_player.py` + `greedy_scorers.py` +
  `greedy_dice.py`
- **Known gap**:
  - F1..F5 feature 公式细节本 spec 未 inline — 引用 source docstring。
    若未来 feature 改动,docstring + spec 双更新。
  - Schema 中 `mcts_pure` 不含 `c_puct` field — 当前 hard-coded
    `DEFAULT_C_PUCT=1.4`,follow-up 加 schema field 暴露(若 ablation
    需要)。
  - Historical ckpt 未在 spec 区分 "current ckpt" vs "frozen baseline" —
    都走 `az` / `cfr` type + ckpt path,语义由 caller / cfg 决定。
