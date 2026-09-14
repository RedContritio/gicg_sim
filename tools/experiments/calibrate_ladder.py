"""Paired-layout baseline cross-play; report observed strength, not assumed order."""

import argparse
from itertools import combinations
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.eval_ladder import BASELINES, evaluation_provenance, make_baseline
from tools.experiments.evaluate_clean import interval
from tools.experiments.skill_abuser import load_skill_catalog
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.outcome import terminal_outcome
from training.paradigms.dmc._eval_scenarios import generate_eval_scenarios


def play_pair(cfg, build_left, build_right, n, seed):
    if n < 1:
        raise ValueError('at least one paired scenario is required')
    scenarios = generate_eval_scenarios(seed, n, cfg.scenario.team_0, cfg.scenario.team_1)
    factory = make_env_factory(cfg, None, seed)
    outcomes, layouts = [], []
    for index, scenario in enumerate(scenarios):
        layout = derive_seed(seed, 'eval-layout', index)
        layouts.append(layout)
        env = factory(index, layout_seed=layout)
        try:
            for side in (0, 1):
                env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
                left = build_left(derive_seed(scenario.env_seed, 'left', side))
                right = build_right(derive_seed(scenario.env_seed, 'right', side))
                for player in (left, right):
                    if hasattr(player, 'game_start'):
                        player.game_start(env.static_obs)
                for _ in range(cfg.paradigm['max_game_steps']):
                    if env.done:
                        break
                    player = left if env.acting_player == side else right
                    action = player.select_action(env)
                    if not 0 <= action < len(env.get_action_refs()):
                        raise ValueError('cross-play returned illegal action')
                    env.step(action)
                if not env.done:
                    raise RuntimeError('cross-play did not reach terminal state')
                outcomes.append(terminal_outcome(env.winner, side))
        finally:
            env.close()
    scores = (np.asarray(outcomes) + 1) / 2
    return {
        'games': len(outcomes),
        'wins': outcomes.count(1),
        'draws': outcomes.count(0),
        'losses': outcomes.count(-1),
        'score': float(scores.mean()),
        'paired_score_ci95': interval(scores),
        'outcomes': outcomes,
        'layout_seeds': layouts,
        'truncated': 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=111000)
    parser.add_argument('--scenarios', type=int, default=32)
    args = parser.parse_args()
    torch.set_num_threads(1)
    cfg = load_cfg(args.config)
    catalog = load_skill_catalog(cfg)
    result = {
        'provenance': provenance(),
        'evaluation': evaluation_provenance(),
        'seed': args.seed,
        'scenarios': args.scenarios,
        'status': 'running',
        'pairs': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for left, right in combinations(BASELINES, 2):
        games = play_pair(
            cfg,
            lambda s: make_baseline(left, s, catalog),
            lambda s: make_baseline(right, s, catalog),
            args.scenarios,
            args.seed,
        )
        result['pairs'].append({'left': left, 'right': right, **games})
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(left, 'vs', right, games['score'], flush=True)
    result['status'] = 'complete'
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
