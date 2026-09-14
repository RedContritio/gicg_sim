"""DMC file-evaluation adapter: real random policies and paired draw-aware scores."""

from types import SimpleNamespace

import numpy as np

from training.paradigms.dmc._eval_periodic import PeriodicEvaluator, _build_baseline_player
from training.core.matchup.outcome import terminal_outcome


def score_interval(outcomes, paired=True):
    values = (np.asarray(outcomes, dtype=float) + 1) / 2
    units = values.reshape(-1, 2).mean(axis=1) if paired else values
    if not len(units):
        raise ValueError('evaluation needs at least one scenario')
    rng = np.random.default_rng(91000)
    means = units[rng.integers(len(units), size=(5000, len(units)))].mean(axis=1)
    return tuple(map(float, np.quantile(means, [0.025, 0.975])))


def play(env, scenario, agent, opponent, side, max_steps):
    env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
    if hasattr(agent, 'rng'):
        agent.rng.seed(scenario.env_seed + side + 17)
    for player in (agent, opponent):
        if hasattr(player, 'game_start'):
            player.game_start(env.static_obs)
    for _ in range(max_steps):
        if env.done:
            break
        player = agent if env.acting_player == side else opponent
        # Preserve the requested policy, including epsilon=1 for uniform random.
        action = player.select_action(env)
        if not 0 <= action < len(env.get_action_refs()):
            raise ValueError('evaluation player returned illegal action')
        env.step(action)
    if not env.done:
        raise RuntimeError('evaluation reached step limit before terminal state')
    winner = env._engine.winner
    return terminal_outcome(winner, side)


class PairedEvaluator(PeriodicEvaluator):
    def _eval_one_baseline(self, agent, name):
        outcomes = []
        sides = (0, 1) if self.cfg.eval.swap_sides else (0,)
        for scenario in self.scenarios:
            env = self._get_env(scenario.team_0, scenario.team_1)
            for side in sides:
                opponent = _build_baseline_player(name, seed=scenario.env_seed + side, dmc_cfg=self.cfg)
                outcomes.append(play(env, scenario, agent, opponent, side, self.cfg.max_game_steps))
        scores = (np.asarray(outcomes) + 1) / 2
        lo, hi = score_interval(outcomes, self.cfg.eval.swap_sides)
        return SimpleNamespace(
            wp_mean=float(scores.mean()),
            wp_swap_p0=float(scores[:: len(sides)].mean()),
            wp_swap_p1=float(scores[1::2].mean()) if len(sides) == 2 else float('nan'),
            n_games=len(outcomes),
            ci95_lo=lo,
            ci95_hi=hi,
            wins=outcomes.count(1),
            draws=outcomes.count(0),
            losses=outcomes.count(-1),
        )


def build_evaluator(cfg):
    return PairedEvaluator(cfg)
