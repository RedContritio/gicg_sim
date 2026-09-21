"""Independent paired-layout D1 development evaluation for semantic checkpoints."""

import argparse
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.loaders import load_player
from tools.experiments.semantic_training.player_loader import register_semantic_loader
from tools.experiments.semantic_training.teams import eval_cases, with_teams, matchup_key
from tools.experiments.semantic_training.decision_budget import DecisionBudget


register_semantic_loader()


_AGENT = None
_CFG = None
_OPPONENT_DEPTH = 1


def _evaluated_checkpoint(checkpoint, player_spec):
    return player_spec.get('ckpt') if player_spec else checkpoint


def initialize(config, checkpoint, opponent_depth=1, player_spec=None):
    global _AGENT, _CFG, _OPPONENT_DEPTH
    _OPPONENT_DEPTH = opponent_depth
    torch.set_num_threads(1)
    _CFG = load_cfg(config)
    if checkpoint == 'teacher-d2':
        _AGENT = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=0)
        return
    spec = dict(player_spec) if player_spec else {'type': 'semantic_rl', 'ckpt': str(checkpoint)}
    _AGENT = load_player(spec)(seed=0)


def game(job):
    from tools.rule_validation.variants import environment_config

    index, _, _, scenario, seed = job[:5]
    cfg = with_teams(_CFG, scenario.team_0, scenario.team_1)
    with environment_config(
        cfg, job[5] if len(job) > 5 else None, derive_seed(seed, 'rule-variant', index), index, split='heldout'
    ) as (cfg, manifest):
        return _game(job, cfg, manifest)


def _game(job, game_cfg, manifest):
    index, side, layout, scenario, seed = job[:5]
    env = make_env_factory(game_cfg, None, seed)(index, layout_seed=derive_seed(seed, 'layout', index * 100 + layout))
    opponent = GreedyPlayer(
        features='F1', depth=_OPPONENT_DEPTH, dice_greedy=True, seed=derive_seed(seed, 'opponent', index * 2 + side)
    )
    try:
        env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
        own_seed = derive_seed(seed, 'own', index * 2 + side)
        if hasattr(_AGENT, 'seed'):
            _AGENT.seed(own_seed)
        elif hasattr(_AGENT, 'rng'):
            _AGENT.rng.seed(own_seed)
        if hasattr(_AGENT, 'game_start'):
            # Optional protocol: semantic agents cache static hook embeddings
            # per game; wrappers may forward the lifecycle to their agent.
            _AGENT.game_start(env.static_obs)
        actions = []
        search_ms = 0.0
        budget = DecisionBudget(_CFG.paradigm['max_game_steps'])
        for _ in budget.iterate(env):
            own = env.acting_player == side
            if own:
                if hasattr(_AGENT, 'last_search_ms'):
                    t0 = time.monotonic()
                    action = _AGENT.select_action(env)
                    search_ms += (time.monotonic() - t0) * 1000.0
                else:
                    action = _AGENT.select_action(env)
            else:
                action = opponent.select_action(env)
            actions.append(env.get_action_identities()[action].tolist())
            env.step(action)
        if not env.done or env.winner not in (0, 1, 2):
            raise RuntimeError('evaluation did not reach valid terminal outcome')
        view = env.export_view()
        timeout = view['round'] >= 10 and all(p['alive_count'] > 0 for p in view['players'])
        return {
            'rule_variant': manifest,
            'timeout_adjudicated': timeout,
            'final_round': view['round'],
            'team_0': scenario.team_0,
            'team_1': scenario.team_1,
            'matchup': matchup_key(scenario.team_0, scenario.team_1),
            'index': index,
            'side': side,
            'layout': layout,
            'win': int(env.winner == side),
            'draw': int(env.winner == 2),
            'score': 1.0 if env.winner == side else 0.0 if env.winner in (0, 1) else 0.5,
            'steps': budget.actions,
            'decisions': budget.decisions,
            'internal_decisions': budget.internal,
            'search_ms_total': search_ms,
            'trajectory_sha256': hashlib.sha256(json.dumps(actions).encode()).hexdigest(),
        }
    finally:
        env.close()


def evaluate(
    config,
    checkpoint,
    output,
    scenarios=64,
    layouts=4,
    workers=8,
    seed=124000,
    opponent_depth=1,
    variants=None,
    player_spec=None,
):
    if opponent_depth not in (1, 2):
        raise ValueError('opponent depth must be 1 or 2')
    if min(scenarios, layouts, workers) < 1:
        raise ValueError('positive budgets required')
    start = time.monotonic()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cfg = load_cfg(config)
    cases = eval_cases(cfg, seed, scenarios)
    jobs = [
        (i, side, layout, case, seed, variants)
        for i, case in enumerate(cases)
        for side in (0, 1)
        for layout in range(layouts)
    ]
    actual_checkpoint = _evaluated_checkpoint(checkpoint, player_spec)
    result = {
        'status': 'running',
        'variants': variants,
        'player_spec': player_spec,
        'seed': seed,
        'opponent_depth': opponent_depth,
        'scenarios': scenarios,
        'layouts': layouts,
        'checkpoint': str(actual_checkpoint) if actual_checkpoint is not None else None,
        'checkpoint_sha256': hashlib.sha256(Path(actual_checkpoint).read_bytes()).hexdigest()
        if actual_checkpoint not in (None, 'teacher-d2')
        else None,
        'scenario': asdict(cfg.scenario),
        'max_game_steps': cfg.paradigm['max_game_steps'],
        'provenance': provenance(),
        'games': [],
    }

    def save():
        result['wall_s'] = time.monotonic() - start
        tmp = output / 'result.tmp'
        tmp.write_text(json.dumps(result, indent=2), encoding='utf-8')
        tmp.replace(output / 'result.json')

    save()
    try:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=initialize, initargs=(config, checkpoint, opponent_depth, player_spec)
        ) as pool:
            for row in pool.map(game, jobs):
                result['games'].append(row)
                if len(result['games']) % 64 == 0:
                    save()
                    print({'games': len(result['games']), 'wall_s': result['wall_s']}, flush=True)
        scores = np.asarray([g['score'] for g in result['games']]).reshape(scenarios, 2, layouts)
        rng = np.random.default_rng(seed)
        sampled = rng.integers(scenarios, size=(10000, scenarios))
        pooled = scores.mean(axis=(1, 2))[sampled].mean(axis=1)
        result['score'] = float(scores.mean())
        result['cluster_bootstrap95'] = np.quantile(pooled, [0.025, 0.975]).tolist()
        result['per_layout'] = scores.mean(axis=(0, 1)).tolist()
        result['paired_layout_delta95'] = {
            str(k): np.quantile(
                (scores[:, :, k] - scores[:, :, 0]).mean(axis=1)[sampled].mean(axis=1), [0.025, 0.975]
            ).tolist()
            for k in range(1, layouts)
        }
        result['per_matchup'] = {
            key: float(np.mean([g['score'] for g in result['games'] if g['matchup'] == key]))
            for key in sorted({g['matchup'] for g in result['games']})
        }
        result['wins'] = sum(g['win'] for g in result['games'])
        result['draws'] = sum(g['draw'] for g in result['games'])
        result['timeout_games'] = sum(g['timeout_adjudicated'] for g in result['games'])
        result['timeout_wins'] = sum(g['timeout_adjudicated'] and g['win'] for g in result['games'])
        result['elimination_wins'] = sum(g['win'] and not g['timeout_adjudicated'] for g in result['games'])
        hashes = np.asarray([g['trajectory_sha256'] for g in result['games']]).reshape(scenarios * 2, layouts)
        result['identical_layout_trajectories'] = int((hashes == hashes[:, :1]).all(axis=1).sum())
        result['status'] = 'complete'
        save()
        print({k: v for k, v in result.items() if k != 'games'}, flush=True)
    except BaseException as error:
        result.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--scenarios', type=int, default=64)
    p.add_argument('--layouts', type=int, default=4)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--seed', type=int, default=124000)
    p.add_argument('--opponent-depth', type=int, choices=(1, 2), default=1)
    p.add_argument(
        '--player-spec',
        type=str,
        default=None,
        help='JSON player spec (default: semantic_rl ckpt). E.g. \'{"type":"az","ckpt":"<path>","n_simulations":16}\'',
    )
    p.add_argument(
        '--variants',
        type=str,
        default=None,
        help='rule-variant catalog path (all games play heldout variants)',
    )
    a = p.parse_args()
    spec = json.loads(a.player_spec) if a.player_spec else None
    evaluate(
        a.config,
        a.checkpoint,
        a.output,
        a.scenarios,
        a.layouts,
        a.workers,
        a.seed,
        a.opponent_depth,
        player_spec=spec,
        variants=a.variants,
    )
