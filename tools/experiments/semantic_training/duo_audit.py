"""Diagnostic D2 disagreements; paired one-action interventions on RL trajectories."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random

import numpy as np

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer, _score_best_response
from training.core.matchup.outcome import terminal_outcome


def game(job):
    index, side, scenario, seed = job
    cfg = with_teams(ev._CFG, scenario.team_0, scenario.team_1)
    env = make_env_factory(cfg, None, seed)(index, layout_seed=derive_seed(seed, 'layout', index))
    agent = ev._AGENT
    teacher = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=seed)
    opponent = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=seed + index * 2 + side)
    rng = random.Random(derive_seed(seed, 'reservoir', index * 2 + side))
    rows, samples = [], []
    bad = 0
    limit = cfg.paradigm['max_game_steps']
    try:
        env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
        agent.game_start(env.static_obs)
        for step in range(limit):
            if env.done:
                break
            if env.acting_player != side:
                env.step(opponent.select_action(env))
                continue
            nn = agent.select_action(env)
            alternative, info = teacher.select_with_info(env)
            alternative = int(alternative)
            score = dict(info['scored']).get(nn)
            if score is None:
                before, events = env.export_view(), env.reward_events(side)
                snap = env.snapshot()
                try:
                    env.step(nn)
                    score = _score_best_response(env, before, events, side, teacher.scorer, 1, True)
                finally:
                    env.restore(snap)
                    env.snapshot_free(snap)
            refs = env.get_action_identities()
            kinds, _ = env.get_legal_actions()
            row = dict(
                game=index * 2 + side,
                step=step,
                side=side,
                nn=nn,
                d2=alternative,
                nn_ref=refs[nn].tolist(),
                d2_ref=refs[alternative].tolist(),
                nn_kind=int(kinds[nn]),
                d2_kind=int(kinds[alternative]),
                gap=float(info['best_score'] - score),
                ends_with_skill=bool(kinds[nn] == 3 and (kinds == 0).any()),
            )
            rows.append(row)
            if row['gap'] > 1e-6:
                bad += 1
                slot = rng.randrange(bad)
                if len(samples) < 2 or slot < 2:
                    item = (env.snapshot(), {**row, 'view': env.export_view()})
                    if len(samples) < 2:
                        samples.append(item)
                    else:
                        env.snapshot_free(samples[slot][0])
                        samples[slot] = item
            env.step(nn)
        if not env.done:
            raise RuntimeError('audit trajectory exceeded budget')
        win = int(env.winner == side)
        probes = []
        for snap, row in samples:
            pairs = []
            for rep in range(4):
                branch_seed = derive_seed(seed, 'branch', (row['game'] * limit + row['step']) * 4 + rep)
                outcomes = {}
                for name in ('nn', 'd2'):
                    env.restore(snap)
                    env.set_simulation_seed(branch_seed)
                    opponent.rng.seed(branch_seed)
                    env.step(row[name])
                    for _ in range(limit):
                        if env.done:
                            break
                        env.step((agent if env.acting_player == side else opponent).select_action(env))
                    if not env.done:
                        raise RuntimeError('audit continuation exceeded budget')
                    outcomes[name] = (terminal_outcome(env.winner, side) + 1) / 2
                pairs.append(outcomes)
            probes.append({**row, 'paired_outcomes': pairs})
        return {'index': index, 'side': side, 'win': win, 'decisions': rows, 'probes': probes}
    finally:
        for snap, _ in samples:
            env.snapshot_free(snap)
        env.close()


def run(config, checkpoint, output, workers=16):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    seed = 144000
    cases = eval_cases(load_cfg(config), seed, 30)
    jobs = [(i, side, case, seed) for i, case in enumerate(cases) for side in (0, 1)]
    with ProcessPoolExecutor(max_workers=workers, initializer=ev.initialize, initargs=(config, checkpoint)) as pool:
        games = list(pool.map(game, jobs))
    rows = [r for g in games for r in g['decisions']]
    probes = [r for g in games for r in g['probes']]
    deltas = [np.mean([p['d2'] - p['nn'] for p in r['paired_outcomes']]) for r in probes]
    result = {
        'status': 'complete',
        'checkpoint': checkpoint,
        'seed': seed,
        'games': games,
        'decisions': len(rows),
        'positive_d2_gap': sum(r['gap'] > 1e-6 for r in rows),
        'mean_d2_gap': float(np.mean([r['gap'] for r in rows])),
        'ends_with_skill': sum(r['ends_with_skill'] for r in rows),
        'probes': len(probes),
        'mean_one_action_win_delta': float(np.mean(deltas)) if deltas else None,
        'positive_probe_delta': int(sum(d > 0 for d in deltas)),
        'negative_probe_delta': int(sum(d < 0 for d in deltas)),
    }
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print({k: v for k, v in result.items() if k != 'games'}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--workers', type=int, default=16)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.workers)
