---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: eval-protocol
subtopic: gauntlet
---

# Gauntlet — `run_matchup` 多 baseline 协议

> 本 subtopic 锚定 gauntlet evaluator 协议 — `run_matchup` 入口 +
> `CellStats` / `MatchupResult` schema + `enumerate_disjoint_teams`
> 算法 + swap_sides 实施细节。
>
> 源 truth:`training/framework/matchup/matchup.py`。

## 1. Scope

本 subtopic 覆盖:

- `run_matchup(players, ...)` 入口签名 + 行为契约
- `mode="fixed"` vs `mode="enumerate_disjoint"` 两种 team 选择
- `_play_cell` 内 cell loop + swap_sides 双倍展开
- `_play_one` 内 game loop + max_game_steps termination
- `CellStats` / `MatchupResult` dataclass schema
- `enumerate_disjoint_teams` 算法:char_pool × team_size →
  unordered disjoint team pair set

不覆盖:

- Baseline player 实施(`load_player` 内 dispatch)— [`./baselines.md`](./baselines.md)
- Service-level job dispatch — [`./service.md`](./service.md)
- 1v1 arena(non-tournament)— [`./arena.md`](./arena.md)

## 2. `run_matchup` 入口

### 2.1 Signature

```python
def run_matchup(
    players: List[dict],     # exactly 2 player specs
    *,
    mode: str,               # "fixed" | "enumerate_disjoint"
    team_0: List[str] | None = None,
    team_1: List[str] | None = None,
    char_pool: List[str] | None = None,
    team_size: int | None = None,
    card_pool: List[str] | None = None,
    games_per_cell: int = 10,
    max_game_steps: int = 400,
    seed: int = 0,
    data_dir: str | None = None,
    deck_padding: dict | None = None,
    pool: object | None = None,    # str | list[str] | None
    swap_sides: bool = True,
) -> MatchupResult
```

### 2.2 SHALL invariants

1. `run_matchup` SHALL `raise ValueError`:
   - `len(players) != 2`
   - `games_per_cell <= 0`
   - `mode=fixed` 缺 `team_0` / `team_1`
   - `mode=enumerate_disjoint` 缺 `char_pool` / `team_size`
   - 未知 `mode`

2. `mode="fixed"` SHALL produce **单 team pair** = `[(team_0, team_1)]`,
   1 个 cell。

3. `mode="enumerate_disjoint"` SHALL call `enumerate_disjoint_teams(
   char_pool, team_size)` 生成所有 unordered disjoint pair(详 §3),
   每个 pair 一个 cell。

4. Player builders SHALL be `load_player(spec)` 一次性 build(SHALL
   NOT per-cell rebuild — ckpt load expensive)。Players 内部 RNG
   per-game seed 由 `_play_cell` 注入。

5. `seed + ti * 10_000` SHALL be base seed for cell `ti`(避免不
   同 cell 共用 RNG seed)。

## 3. `enumerate_disjoint_teams`

### 3.1 Algorithm

```
For team_0 in combinations(char_pool, team_size):
    remaining = char_pool - team_0
    For team_1 in combinations(remaining, team_size):
        key = frozenset({frozenset(team_0), frozenset(team_1)})
        if key already seen: skip
        else: emit (team_0, team_1), record key
```

### 3.2 SHALL invariants

1. `team_size * 2 > len(char_pool)` SHALL `raise ValueError` —
   disjoint 不可行。

2. `team_size <= 0` SHALL `raise ValueError`。

3. Output SHALL fold by **unordered-pair symmetry** —
   `(team_A, team_B)` 与 `(team_B, team_A)` 视为同一 matchup(`frozenset`
   key)。caller 通过 `swap_sides=True` 处理 side-bias。

4. 5-char pool + team_size=2 SHALL yield 15 matchups(C(5,2) × C(3,2)
   / 2)。caller × 2(swap_sides)→ 30 game configurations × games_per_cell。

## 4. `_play_cell` — cell loop + swap_sides

### 4.1 Behavior

```
n_games = (2 * games_per_cell) if swap_sides else games_per_cell
For g in range(n_games):
    primary_plays_team_1 = swap_sides and (g % 2 == 1)
    seed = base_seed + g

    env = GicgEnv(team_0, team_1, card_pool, seed, ...)
    env.reset(seed)
    Try:
        p_primary = builder_0(seed)
        p_secondary = builder_1(seed + 10_000)
        If primary plays team_0:
            winner = _play_one(env, p_primary, p_secondary, max_game_steps)
            primary_side = 0
        Else:
            winner = _play_one(env, p_secondary, p_primary, max_game_steps)
            primary_side = 1

        Tally: winner == primary_side → wins,
               == (1 - primary_side) → losses, else → draws
    Finally:
        env.close()
```

### 4.2 SHALL invariants

1. `swap_sides=True` SHALL double `n_games`(2 × games_per_cell),
   alternating which side `players[0]`(challenger / primary)plays。

2. `swap_sides=False` SHALL play `games_per_cell` games,primary
   always plays team_0(CFR pinned-sides 兼容)。

3. Stats SHALL count from **players[0] / primary perspective**:
   - `wins`:primary won the game
   - `losses`:primary lost
   - `draws`:draw

4. Each game SHALL get fresh `GicgEnv` instance(env.close() in
   `finally`)— SHALL NOT reuse env across games(否则 engine state
   不干净 + risk DSL cache 副作用)。

5. Player builders called with **distinct seeds per game**(`seed` /
   `seed + 10_000`)— builders 是 stateful(RNG)— SHALL NOT race
   on shared seed。

## 5. `_play_one` — game loop

### 5.1 Behavior

```
While env._engine.phase == PHASE_SELECT_ACTIVE:
    env.step(0)
    If env.done: return env._engine.winner

For step in range(max_game_steps):
    If env.done: return env._engine.winner
    acting = env.acting_player
    player = p0 if acting == 0 else p1
    action_idx = player.select_action(env)
    _, _, done, step_info = env.step(action_idx)
    If step_info.get('need_target'):
        raise RuntimeError("matchup: legacy PendingCardTarget path hit")

If not env.done:
    raise RuntimeError(f"matchup: game did not terminate within max_game_steps={max_game_steps}")
```

### 5.2 SHALL invariants

1. `PHASE_SELECT_ACTIVE`(phase=1)SHALL be handled by `env.step(0)`
   loop — 初始 active char 选 0(简化 — 未来若需要 player 决策初
   始 active,SHALL 走 player.select_action)。

2. `need_target=True` in step_info SHALL `raise RuntimeError` —
   legacy PendingCardTarget path 已废,任何残留触发 SHALL crash 而
   非 silent。

3. `max_game_steps` exhaustion without `env.done` SHALL `raise
   RuntimeError` — eval 必须 terminate(timeout 即 bug,SHALL NOT
   silent 视为 draw)。

4. Player `select_action` SHALL return valid `action_idx` in
   `[0, n_legal)`,SHALL NOT raise within game(player 内部错误
   propagate)。

## 6. Schema dataclasses

### 6.1 `CellStats`

```
wins: int       # players[0] / primary wins (after swap_sides adjust)
losses: int
draws: int
wall_s: float

n_games (property): wins + losses + draws
win_rate (property): wins / (n_games - draws), 0.5 if all draws
to_dict() → {wins, losses, draws, n_games, win_rate (rounded 4),
              wall_s (rounded 2)}
```

### 6.2 `MatchupResult`

```
players: List[dict]               # original specs
aggregate: CellStats               # all cells summed
per_cell: List[dict]               # one dict per cell:
                                   # {team_0, team_1, **cell_stats.to_dict()}
wall_s: float

to_dict() → {players, wall_s, aggregate, per_cell}
```

### 6.3 SHALL invariants

1. `win_rate` SHALL exclude draws(`(n_games - draws)` denominator)。
   全 draw cell return 0.5(epsilon-safe)。

2. `aggregate.win_rate` SHALL be over all decisive games across cells
   (sum-wins / sum-decisive),SHALL NOT 是 cell-level rates 的算术
   平均(后者会 cell-size 不一致时 bias)。

3. `to_dict()` 输出 SHALL be JSON-serializable(no numpy / dataclass
   leakage)— 用于 JSONL append。

## 7. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 4 + SHALL 7 + SHALL 9 —
  gauntlet 锚点
- [`./service.md`](./service.md) §4 — `run_gauntlet_job` 内 invoke
- [`./baselines.md`](./baselines.md) — `load_player` 调度
- [`env-config/lifecycle`](../env-config/lifecycle.md) — `GicgEnv`
  实例化 cfg
- [`changes/archive/0011-pool-versioning`](../../changes/archive/0011-pool-versioning/) —
  `pool` / `deck_padding` 字段

## 8. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`training/framework/matchup/matchup.py`
- **Known gap**:`PHASE_SELECT_ACTIVE` 时 `env.step(0)` 强制选 0 —
  未来 player 决策初始 active 时 SHALL spec 化 player 参与;目前是
  hard-coded 简化。
