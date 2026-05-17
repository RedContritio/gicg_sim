---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: eval-protocol
subtopic: arena
---

# Arena — `arena_match` 1v1 head-to-head 协议

> 本 subtopic 锚定 arena evaluator 协议 — `arena_match` 入口 +
> `ArenaResult` schema + AZ self-play 内 ckpt 替换决定的 consumer
> pattern + 与 gauntlet 的边界区分原则。
>
> 源 truth:`training/az/arena.py`。

## 1. Scope

本 subtopic 覆盖:

- `arena_match` 入口签名 + 行为契约
- `ArenaResult` dataclass schema
- AZ self-play 周期 ckpt 替换决定的 consumer pattern
- 与 gauntlet 边界(arena = 1v1 单 team pair vs gauntlet = N
  baseline 多 team pair)

不覆盖:

- AZ ckpt 替换 threshold(`win_rate ≥ 0.55` 之类策略)— AZ paradigm
  dossier
- Gauntlet 多 baseline tournament — [`./gauntlet.md`](./gauntlet.md)
- Baseline player 实施 — [`./baselines.md`](./baselines.md)

## 2. `arena_match` 入口

### 2.1 Signature

```python
def arena_match(
    challenger,                        # agent instance (eval_state + game_start/end)
    champion,                          # agent instance
    env_factory: Callable[[int], GicgEnv],   # game_idx -> fresh env
    n_games: int,
    *,
    max_game_steps: int = 400,
    seed: int = 0,
    mcts_config=None,                  # optional: enable MCTS search
    card_pool_spec=None,               # required iff mcts_config is set (IS-MCTS deterministic)
) -> ArenaResult
```

### 2.2 SHALL invariants

1. `arena_match` SHALL `raise ValueError` if `n_games <= 0`。

2. `env_factory(game_idx)` SHALL be called **per game** to produce a
   fresh env(SHALL NOT reuse env handle across games)。Factory 内
   部决定 team / card_pool / pool / scenario seeding。

3. `challenger_side` SHALL alternate per game(`g % 2`)— g=0
   challenger plays P0,g=1 plays P1。`n_games` 应为偶数以保证 side
   balance(spec 不强制,但 best practice)。

4. Win/loss/draw SHALL be tallied from **challenger perspective**:
   - `challenger_wins`:winner == challenger_side
   - `champion_wins`:winner == (1 - challenger_side)
   - `draws`:winner == 2

5. `arena_match` SHALL NOT use `swap_sides` flag like gauntlet does
   — arena 总是 1v1 双向 swap(challenger_side 由 g % 2 强制 alternate);
   gauntlet 的 `swap_sides=False` mode 是 CFR-specific 让步,arena 不
   提供。

6. `mcts_config` + `card_pool_spec` SHALL be **both** provided or
   **both** None。MCTS enable 需要 `card_pool_spec`(IS-MCTS
   determinization 用)。

## 3. `_play_one` — arena game loop

### 3.1 Behavior

```
p0_agent.game_start(env.static_obs)
p1_agent.game_start(env.static_obs)
try:
    while env._engine.phase == PHASE_SELECT_ACTIVE:
        env.step(0)
        if env.done: return winner

    for step_idx in range(max_game_steps):
        if env.done: return winner
        acting = env.acting_player
        agent = p0_agent if acting == 0 else p1_agent

        if mcts_config is set:
            action_idx = mcts_search(env, agent, card_pool_spec, rng,
                                     viewing_player=acting, ...)
        else:
            refs = env.get_action_refs()
            payments = env.get_legal_action_payments()
            dyn_obs = env._get_obs()
            prior, _value = agent.eval_state(dyn_obs, refs, payments)
            action_idx = int(np.argmax(prior))

        _, _, done, step_info = env.step(action_idx)
        if step_info.get('need_target'):
            raise RuntimeError("arena: legacy PendingCardTarget path hit — unsupported")

    if not env.done:
        raise RuntimeError(f"arena: game did not terminate within max_game_steps={max_game_steps}")
    return env._engine.winner
finally:
    p0_agent.game_end()
    p1_agent.game_end()
```

### 3.2 SHALL invariants

1. Agent SHALL implement:
   - `game_start(static_obs)` — once per game(arena calls before
     PHASE_SELECT_ACTIVE)
   - `eval_state(dyn_obs, refs, payments)` → `(prior, value)`
   - `game_end()` — once per game(finally block)

2. `n_legal == 0` on non-terminal state SHALL `raise RuntimeError`
   — defensive guard,engine 端不应该出现 0 legal actions in-progress。

3. `need_target=True` in step_info SHALL `raise RuntimeError`(同
   gauntlet,legacy path hit)。

4. `max_game_steps` exhaustion without `done` SHALL `raise
   RuntimeError`(同 gauntlet,timeout = bug)。

5. `game_end()` SHALL run in `finally` — exception 也调用,保证
   agent state clean。

## 4. `ArenaResult` schema

### 4.1 Dataclass

```
challenger_wins: int
champion_wins: int
draws: int
n_games: int
wall_s: float = 0.0
per_game_s: list[float] = []

challenger_win_rate (property):
    decisive = n_games - draws
    if decisive == 0: return 0.5
    return challenger_wins / decisive
```

### 4.2 SHALL invariants

1. `challenger_win_rate` SHALL exclude draws(`(n_games - draws)`
   denominator),全 draw return 0.5(同 gauntlet `CellStats`
   convention)。

2. `per_game_s` SHALL track wall-clock per individual game(`round(...,
   3)`),用于 outlier 诊断(MCTS 偶发慢 game)。

3. `n_games` SHALL equal `challenger_wins + champion_wins + draws`
   — caller responsibility check;arena 函数本身不 assert。

## 5. AZ self-play consumer pattern

### 5.1 Usage

AZ training driver(`training/az/async_loop.py` / driver loop)周期
build `arena_match(challenger=new_ckpt_agent, champion=current_ckpt_agent,
env_factory, n_games=N)`,read `result.challenger_win_rate`,决定是
否替换 ckpt(threshold by AZ paradigm dossier,通常 ≥ 0.55)。

### 5.2 SHALL invariants

1. Arena 不 emit JSONL(与 gauntlet 不同)— 直接返回
   `ArenaResult`,caller(AZ driver)decide 是否记录到
   `metrics.jsonl`。

2. Arena 不通过 socket service — embedded in训练 process(无 IPC 开
   销;ckpt 替换在 train loop critical path)。

3. Arena `mcts_config` 启用与否由 paradigm dossier 决定 — AZ 通常
   `mcts_search` 启用(评估反映 search-augmented 强度);CFR / DMC
   通常 argmax direct(评估 raw network strength)。

## 6. Arena vs Gauntlet 区分

| 维度 | Arena | Gauntlet |
|---|---|---|
| 入口 | `training/az/arena.py::arena_match` | `training/framework/matchup/matchup.py::run_matchup` |
| Opponents | 1 个(challenger vs champion) | N(challenger vs N baselines,各自 matchup) |
| Team pair | 1(env_factory 决定) | 1 (fixed) 或 K(enumerate_disjoint) |
| Swap-sides | 强制 alternating(g % 2) | 可选 `swap_sides=True/False` |
| Output | `ArenaResult` 返回值 | JSONL append + `MatchupResult` |
| Use case | AZ ckpt 替换决定 | 周期 baseline strength 评估 |
| Service IPC | 否(embed in train process) | 通过 eval_service socket dispatch |
| Player builder | Agent instance 直接传入 | spec dict + `load_player` registry |

### 6.1 SHALL invariants

1. Arena SHALL NOT be re-implemented as a wrapper over `run_matchup`
   — 两者有真实差异(IPC / use case),融合会损失明确性。

2. Arena 与 gauntlet SHALL share **同一 GicgEnv 实例化语义**(与
   [`env-config`](../env-config/spec.md) 对齐)。差异仅在 player
   wrapping 与 result aggregation。

3. AZ ckpt 替换 threshold(`≥ X` win rate)SHALL be paradigm-dossier
   level,SHALL NOT 硬编码在 `arena_match` 函数内。

## 7. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 5 — arena 锚点
- [`./gauntlet.md`](./gauntlet.md) — gauntlet 协议,本 spec §6 对
  比表
- [`env-config/lifecycle`](../env-config/lifecycle.md) —
  `env_factory` 内 `GicgEnv` cfg
- AZ paradigm dossier(P2 落地)— ckpt 替换 threshold 与
  `mcts_config` 细节

## 8. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`training/az/arena.py`
- **Known gap**:`env_factory(game_idx)` 接口未在本 spec 治理具体
  cfg(team / pool / seed 派生),由 caller / AZ driver 内部 contract
  决定。
