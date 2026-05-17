"""MCTSConfig + MCTSProfile + compute_annealed_lambda."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MCTSConfig:
    n_rollouts: int = 400
    c_puct: float = 1.4
    dirichlet_alpha: float = 0.3
    dirichlet_eps: float = 0.25
    temperature: float = 1.0
    temperature_switch_step: int = 15
    max_rollout_depth: int = 400
    discovery_checkpoints: tuple = (50, 100, 200, 400)
    parallel_rollouts: int = 1
    value_mix_lambda: float = 1.0
    prior_mix_lambda: float = 1.0
    lambda_anneal_games: int = 0
    lambda_start: float = 0.0
    lambda_end: float = 0.8
    profile: bool = True
    backend: str = 'python'


@dataclass
class MCTSProfile:
    """Per-search timing breakdown."""

    n_rollouts: int = 0
    n_restore: int = 0
    n_determinize: int = 0
    n_eval: int = 0
    n_rollout: int = 0
    n_rollout_steps: int = 0
    n_env_step: int = 0
    n_env_query: int = 0
    n_commit: int = 0
    n_d1_trigger: int = 0
    n_d1_new_actions: int = 0

    restore_s: float = 0.0
    determinize_s: float = 0.0
    eval_s: float = 0.0
    rollout_s: float = 0.0
    env_step_s: float = 0.0
    env_query_s: float = 0.0
    descend_s: float = 0.0
    eval_send_s: float = 0.0
    eval_recv_s: float = 0.0
    commit_s: float = 0.0

    def as_dict(self) -> dict:
        total = (
            self.determinize_s
            + self.restore_s
            + self.descend_s
            + self.eval_s
            + self.rollout_s
            + self.env_step_s
            + self.env_query_s
            + self.eval_send_s
            + self.eval_recv_s
            + self.commit_s
        )
        d: dict = {'total_s': round(total, 6), 'n_rollouts': self.n_rollouts}

        _cats = [
            ('restore', self.n_restore, self.restore_s),
            ('determinize', self.n_determinize, self.determinize_s),
            ('eval', self.n_eval, self.eval_s + self.eval_send_s + self.eval_recv_s),
            ('rollout', self.n_rollout, self.rollout_s),
            ('env_step', self.n_env_step, self.env_step_s),
            ('env_query', self.n_env_query, self.env_query_s),
            ('descend', 0, self.descend_s),
            ('commit', self.n_commit, self.commit_s),
        ]
        for name, n, s in _cats:
            if n > 0 or s > 0:
                d[f'n_{name}'] = n
                d[f'{name}_s'] = round(s, 6)
        if self.n_rollout_steps > 0:
            d['n_rollout_steps'] = self.n_rollout_steps
        if self.n_d1_trigger > 0 or self.n_d1_new_actions > 0:
            d['n_d1_trigger'] = self.n_d1_trigger
            d['n_d1_new_actions'] = self.n_d1_new_actions

        if total > 0:
            ctypes_s = self.env_step_s + self.env_query_s + self.restore_s + self.determinize_s
            eval_total_s = self.eval_s + self.eval_send_s + self.eval_recv_s
            d['pct_rollout'] = round(100.0 * self.rollout_s / total, 1)
            d['pct_ctypes'] = round(100.0 * ctypes_s / total, 1)
            d['pct_eval'] = round(100.0 * eval_total_s / total, 1)
        return d


def compute_annealed_lambda(config: MCTSConfig, game_idx: int) -> float:
    """Compute the effective lambda for a given game index."""
    if config.lambda_anneal_games <= 0:
        raise ValueError(
            f'compute_annealed_lambda called with '
            f'lambda_anneal_games={config.lambda_anneal_games}; '
            f'caller should check before calling'
        )
    frac = min(1.0, game_idx / config.lambda_anneal_games)
    return config.lambda_start + (config.lambda_end - config.lambda_start) * frac
