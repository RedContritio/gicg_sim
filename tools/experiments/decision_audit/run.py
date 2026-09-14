"""Audit NN/D1 disagreements and paired continuations on sampled visited states."""

import argparse
import hashlib
import json
from pathlib import Path
import random

import numpy as np
import torch

from tools.experiments.evaluate_history import builder
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.greedy_scorers import SCORERS
from training.core.matchup.outcome import terminal_outcome
from training.paradigms.dmc._eval_scenarios import generate_eval_scenarios


def d1(seed):
    return GreedyPlayer(features='F1', depth=1, dice_greedy=True, seed=seed)


def immediate(env, action, me):
    before = env.export_view()
    snap = env.snapshot()
    try:
        env.step(action)
        return {
            'f1': SCORERS['F1'](before, env.export_view(), None, None, me),
            'wins_now': bool(env.done and env.winner == me),
        }
    finally:
        env.restore(snap)
        env.snapshot_free(snap)


def continuation(env, snap, first, me, own, opponent, seed, limit):
    env.restore(snap)
    env.set_simulation_seed(seed)
    own.rng.seed(derive_seed(seed, 'own'))
    opponent.rng.seed(derive_seed(seed, 'opponent'))
    env.step(first)
    for _ in range(limit):
        if env.done:
            return terminal_outcome(env.winner, me)
        player = own if env.acting_player == me else opponent
        env.step(player.select_action(env))
    raise RuntimeError('continuation exceeded terminal step budget')


def audit(config, checkpoint, output, scenarios=8, seed=118000, per_game=2, repeats=2):
    if min(scenarios, per_game, repeats) < 1:
        raise ValueError('positive sample budgets required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    cfg = load_cfg(config)
    agent = builder(cfg, checkpoint)(seed)
    factory = make_env_factory(cfg, None, seed)
    limit = cfg.paradigm['max_game_steps']
    layouts = generate_eval_scenarios(seed, scenarios, cfg.scenario.team_0, cfg.scenario.team_1)
    result = {
        'status': 'running',
        'provenance': provenance(),
        'seed': seed,
        'checkpoint': str(checkpoint),
        'checkpoint_sha256': hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        'tool_sha256': {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path('tools/experiments/decision_audit').glob('*.py'))
        },
        'scenarios': scenarios,
        'per_game': per_game,
        'repeats': repeats,
        'games': [],
        'states': [],
    }

    def save():
        tmp = output / 'result.tmp'
        tmp.write_text(json.dumps(result, indent=2), encoding='utf-8')
        tmp.replace(output / 'result.json')

    save()
    try:
        for index, scenario in enumerate(layouts):
            for side in (0, 1):
                env = factory(index, layout_seed=derive_seed(seed, 'eval-layout', index))
                samples = []
                rng = random.Random(derive_seed(seed, 'reservoir', index * 2 + side))
                opponent = d1(derive_seed(seed, 'game-opponent', index * 2 + side))
                teacher = d1(derive_seed(seed, 'teacher', index * 2 + side))
                game = {'index': index, 'side': side, 'decisions': [], 'divergences': 0}
                try:
                    env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
                    agent.game_start(env.static_obs)
                    for step in range(limit):
                        if env.done:
                            break
                        if env.acting_player != side:
                            env.step(opponent.select_action(env))
                            continue
                        refs = env.get_action_refs()
                        payments = env.get_legal_action_payments()
                        q = agent._forward_logits(env._get_obs(), refs, payments, len(refs)).cpu().numpy()
                        if not np.isfinite(q).all():
                            raise ValueError('nonfinite Q values')
                        nn = int(q.argmax())
                        chosen, info = teacher.select_with_info(env)
                        a, b = immediate(env, nn, side), immediate(env, chosen, side)
                        row = {
                            'game': index * 2 + side,
                            'step': step,
                            'side': side,
                            'nn': nn,
                            'd1': chosen,
                            'nn_ref': refs[nn].tolist(),
                            'd1_ref': refs[chosen].tolist(),
                            'nn_payment': payments[nn].tolist(),
                            'd1_payment': payments[chosen].tolist(),
                            'nn_q': float(q[nn]),
                            'd1_q': float(q[chosen]),
                            'nn_effect': a,
                            'd1_effect': b,
                            'f1_gap': info['best_score'] - a['f1'],
                            'ends_with_skill': bool(refs[nn, 0] == 3 and (refs[:, 0] == 0).any()),
                            'payment_only': bool(nn != chosen and np.array_equal(refs[nn], refs[chosen])),
                        }
                        game['decisions'].append(row)
                        if nn != chosen:
                            game['divergences'] += 1
                            slot = rng.randrange(game['divergences'])
                            if len(samples) < per_game or slot < per_game:
                                item = (env.snapshot(), row.copy(), env.export_view())
                                if len(samples) < per_game:
                                    samples.append(item)
                                else:
                                    env.snapshot_free(samples[slot][0])
                                    samples[slot] = item
                        env.step(nn)
                    if not env.done:
                        raise RuntimeError('audit game exceeded terminal step budget')
                    game['outcome'] = terminal_outcome(env.winner, side)
                    result['games'].append(game)
                    for snap, row, view in samples:
                        row['view'] = view
                        row['continuations'] = {}
                        for mode in ('nn', 'd1'):
                            own = agent if mode == 'nn' else d1(0)
                            other = d1(0)
                            pairs = []
                            for rep in range(repeats):
                                branch_seed = derive_seed(
                                    seed, 'continuation', (row['game'] * limit + row['step']) * repeats + rep
                                )
                                pairs.append(
                                    {
                                        name: continuation(env, snap, row[name], side, own, other, branch_seed, limit)
                                        for name in ('nn', 'd1')
                                    }
                                )
                            row['continuations'][mode] = pairs
                        result['states'].append(row)
                    save()
                    print(f'games={len(result["games"])} branch_states={len(result["states"])}', flush=True)
                finally:
                    for snap, _, _ in samples:
                        env.snapshot_free(snap)
                    env.close()
        result['status'] = 'complete'
        save()
    except BaseException as error:
        result.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--scenarios', type=int, default=8)
    parser.add_argument('--seed', type=int, default=118000)
    parser.add_argument('--per-game', type=int, default=2)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    audit(args.config, args.checkpoint, args.output, args.scenarios, args.seed, args.per_game, args.repeats)
