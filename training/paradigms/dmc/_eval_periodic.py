"""Periodic eval for DMC ckpts (tools/eval/ckpt + tools/eval/daemon).

Per decision #8: every ``eval.interval_minutes`` of wall time,
- Replay fixed-seed scenarios against F1-D2 + F1-D4 baselines
- Each scenario played twice (swap_sides=True): agent on side 0 + agent on side 1
- Record WP per baseline (mean over both sides) + Wilson 95% CI

Relocated from ``training/paradigms/dmc/legacy/eval/periodic_eval.py``
(FU-W4-DMC-pt2): the standalone evaluator + daemon are the only callers,
so the module lives alongside them under ``tools/eval/``. The unified
training-pipeline driver uses ``training.core.eval`` instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from gicg_env import GicgEnv
from training.paradigms.dmc._eval_scenarios import EvalScenario, generate_eval_scenarios
from training.core.matchup.greedy_player import GreedyPlayer
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._run_config import DmcConfig, EvalConfig


@dataclass
class BaselineResult:
    name: str
    n_games: int
    wins: int
    losses: int
    draws: int
    wp_mean: float
    wp_swap_p0: float
    wp_swap_p1: float
    ci95_lo: float
    ci95_hi: float


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _build_baseline_player(name: str, seed: int = 0, *, dmc_cfg=None):
    """Construct a baseline opponent by name.

    Supported:
      - 'random'     : RandomPlayer (floor sanity per review D.3)
      - 'F1-D<n>'    : GreedyPlayer features=F1 depth=n dice_greedy=True
      - 'dmc:<path>' : Frozen DmcAgent loaded from ckpt path. dmc_cfg required.
    """
    if name == 'random':
        from training.paradigms.dmc._opponent import RandomPlayer

        return RandomPlayer(seed=seed)
    if name.startswith('F1-D'):
        depth = int(name[len('F1-D') :])
        return GreedyPlayer(features='F1', depth=depth, dice_greedy=True, seed=seed)
    if name.startswith('dmc:'):
        if dmc_cfg is None:
            raise ValueError(f'baseline {name!r} requires dmc_cfg (pass via PeriodicEvaluator)')
        from training.core.checkpoint import load_net_state_dict

        ckpt_path = name[len('dmc:') :]
        opp = DmcAgent(dmc_cfg.agent, device=dmc_cfg.device, lr=dmc_cfg.learning_rate, epsilon=0.0)
        # W1-T4: load via shared helper so 'net.' wrapper prefix is stripped
        # uniformly (pre-W1-T4 this path silently skipped the strip, latent
        # bug under InfServer-wrapper save paths)。
        state_dict = load_net_state_dict(ckpt_path, map_location=dmc_cfg.device)
        opp.net.load_state_dict(state_dict)
        opp.net.eval()
        return opp
    raise ValueError(f'unknown baseline name: {name!r}')


def _play_one_scenario(
    cfg: DmcConfig,
    scenario: EvalScenario,
    agent: DmcAgent,
    opponent,
    *,
    agent_side: int,
    max_steps: int,
    env: GicgEnv,
) -> int:
    """Play one fixed-seed scenario. Returns +1/-1/0 for agent win/loss/draw.

    swap_sides 协议: agent_side 翻 (0 / 1) 但 team_0 / team_1 不翻 — 这样
    case agent_side=0 是 "agent 拿 team_0 走先手", case agent_side=1 是
    "agent 拿 team_1 走后手"。turn-order 与角色 bias 解耦:同 baseline 的
    镜像对照 (case1 vs case2) 理论 50% wp 当 agent==baseline。
    review D.2 修复 — 旧版同时翻 team 列表让 agent 总走 team_0,导致
    "先后手平均不能消去 turn-order bias"。

    D.4: env 现在由调用方注入 + reset(seed) 复用,不再 per-scenario 构造
    (engine.reset_dynamic cheap, no DSL reload)。
    """
    # review D.5: 3-axis seed reset. Backward compat: if scenario didn't
    # provide deck seeds (generator pre-D.5), fall back to single env_seed.
    deck_seeds = None
    if scenario.deck_seed_p0 is not None and scenario.deck_seed_p1 is not None:
        deck_seeds = (scenario.deck_seed_p0, scenario.deck_seed_p1)
    env.reset(seed=scenario.env_seed, deck_seeds=deck_seeds)
    # C.7: 不 skip PHASE_SELECT_ACTIVE — agent 自己出"选初始角色"决策。
    if env.done:
        return _z(env._engine.winner, agent_side)

    agent.game_start(env.static_obs)
    if hasattr(opponent, 'game_start'):
        opponent.game_start(env.static_obs)

    for _ in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        acting = env.acting_player
        if acting == agent_side:
            # eval-time: ε=0 (pure argmax)
            saved_eps = agent.epsilon
            agent.epsilon = 0.0
            try:
                action_idx = agent.select_action(env)
            finally:
                agent.epsilon = saved_eps
        else:
            action_idx = opponent.select_action(env)
        if action_idx < 0 or action_idx >= len(kinds):
            action_idx = 0
        env.step(action_idx)
    return _z(env._engine.winner, agent_side)


def _z(winner: int, perspective: int) -> int:
    if winner < 0:
        return 0
    if winner == perspective:
        return 1
    if winner == 2:
        return 0
    return -1


class PeriodicEvaluator:
    """Hold pre-generated scenarios + run eval rounds on demand.

    D.4: env 按 (team_0, team_1) cache 复用,reset(seed) 重置 dynamic
    state。Stage 3 fixed teams → 1 个 env 复用 512 次 (250× 加速)。
    Stage 4 char_pool 抽样后 ~90 个 env 仍 5× 受益。
    """

    def __init__(self, cfg: DmcConfig):
        self.cfg = cfg
        self.scenarios = generate_eval_scenarios(
            seed=cfg.eval.scenarios_seed,
            n=cfg.eval.n_scenarios,
            team_0=cfg.scenario.team_0,
            team_1=cfg.scenario.team_1,
            char_pool=cfg.scenario.char_pool,
            team_size=cfg.scenario.team_size,
            disjoint_teams=cfg.scenario.disjoint_teams,
        )
        self._env_cache: dict[tuple, GicgEnv] = {}

    def _get_env(self, team_0: list[str], team_1: list[str]) -> GicgEnv:
        """Lookup or build env keyed on (tuple(team_0), tuple(team_1))."""
        key = (tuple(team_0), tuple(team_1))
        env = self._env_cache.get(key)
        if env is None:
            from training.core.scenario import decks_arg

            env = GicgEnv(
                team_0=team_0,
                team_1=team_1,
                card_pool=self.cfg.scenario.card_pool,
                seed=self.cfg.seed,
                data_dir=self.cfg.scenario.data_dir or 'data',
                max_rounds=self.cfg.scenario.max_rounds,
                obs_mask=self.cfg.scenario.obs_mask,
                deck_padding=self.cfg.scenario.deck_padding,
                pool=self.cfg.scenario.pool,
                decks=decks_arg(self.cfg.scenario.deck_0, self.cfg.scenario.deck_1),
            )
            self._env_cache[key] = env
        return env

    def close(self) -> None:
        """Close all cached envs. Call once before discarding evaluator."""
        for env in self._env_cache.values():
            env.close()
        self._env_cache.clear()

    def run_once(self, agent: DmcAgent) -> dict[str, BaselineResult]:
        """Run a full eval round; return dict of baseline name -> result."""
        results: dict[str, BaselineResult] = {}
        for name in self.cfg.eval.baselines:
            results[name] = self._eval_one_baseline(agent, name)
        return results

    def _eval_one_baseline(self, agent: DmcAgent, name: str) -> BaselineResult:
        N = len(self.scenarios)
        wins_p0 = losses_p0 = draws_p0 = 0
        wins_p1 = losses_p1 = draws_p1 = 0
        for s in self.scenarios:
            env = self._get_env(s.team_0, s.team_1)
            opp_p0 = _build_baseline_player(name, seed=s.env_seed, dmc_cfg=self.cfg)
            outcome_p0 = _play_one_scenario(
                self.cfg,
                s,
                agent,
                opp_p0,
                agent_side=0,
                max_steps=self.cfg.max_game_steps,
                env=env,
            )
            if outcome_p0 > 0:
                wins_p0 += 1
            elif outcome_p0 < 0:
                losses_p0 += 1
            else:
                draws_p0 += 1

            if self.cfg.eval.swap_sides:
                opp_p1 = _build_baseline_player(name, seed=s.env_seed + 1, dmc_cfg=self.cfg)
                outcome_p1 = _play_one_scenario(
                    self.cfg,
                    s,
                    agent,
                    opp_p1,
                    agent_side=1,
                    max_steps=self.cfg.max_game_steps,
                    env=env,
                )
                if outcome_p1 > 0:
                    wins_p1 += 1
                elif outcome_p1 < 0:
                    losses_p1 += 1
                else:
                    draws_p1 += 1

        n_games = N + (N if self.cfg.eval.swap_sides else 0)
        total_wins = wins_p0 + wins_p1
        total_losses = losses_p0 + losses_p1
        total_draws = draws_p0 + draws_p1

        # WP: count win=1, draw=0.5, loss=0
        wp_p0 = (wins_p0 + 0.5 * draws_p0) / max(N, 1)
        wp_p1 = (wins_p1 + 0.5 * draws_p1) / max(N, 1) if self.cfg.eval.swap_sides else float('nan')

        if self.cfg.eval.swap_sides:
            wp_mean = (wp_p0 + wp_p1) / 2
        else:
            wp_mean = wp_p0

        ci_lo, ci_hi = _wilson_ci(total_wins, n_games)

        return BaselineResult(
            name=name,
            n_games=n_games,
            wins=total_wins,
            losses=total_losses,
            draws=total_draws,
            wp_mean=wp_mean,
            wp_swap_p0=wp_p0,
            wp_swap_p1=wp_p1,
            ci95_lo=ci_lo,
            ci95_hi=ci_hi,
        )
