"""Exploratory early L6 plays, readable traces and paired one-action interventions."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer

CARDS = ('乘胜追击', '以攻代守', '以逸待劳')


def board(env):
    view = env.export_view()
    return dict(
        round=view['round'],
        hp=[[c['hp'] for c in p['chars']] for p in view['players']],
        active=[p['active_char'] for p in view['players']],
        dice=[env.dice_counts(p).tolist() for p in (0, 1)],
    )


def game(job):
    index, side, case, seed, probe_step, repetitions = job
    cfg = with_teams(ev._CFG, case.team_0, case.team_1)
    env = make_env_factory(cfg, None, seed)(index)
    agent = ev._AGENT
    opponent = GreedyPlayer(
        features='F1', depth=2, dice_greedy=True, seed=derive_seed(seed, 'opponent', index * 2 + side)
    )
    teacher = GreedyPlayer(
        features='F1', depth=2, dice_greedy=True, seed=derive_seed(seed, 'teacher', index * 2 + side)
    )
    trace, early, snap, intervention = [], [], None, None
    limit = cfg.paradigm['max_game_steps']
    try:
        env.reset(seed=case.env_seed, deck_seeds=(case.deck_seed_p0, case.deck_seed_p1))
        agent.game_start(env.static_obs)
        starting = env.export_view()
        for step in range(limit):
            if env.done:
                break
            player = env.acting_player
            action = (agent if player == side else opponent).select_action(env)
            labels = env.get_action_labels()
            label = labels[action]
            before = board(env)
            if player == side and before['round'] <= 2 and label[0] == 'Card' and label[1] in CARDS:
                alternative = int(teacher.select_action(env))
                item = dict(
                    step=step,
                    round=before['round'],
                    card=label[1],
                    action=action,
                    d2_action=alternative,
                    d2_label=labels[alternative],
                    d2_disagrees=labels[alternative][:2] != label[:2],
                )
                early.append(item)
                if step == probe_step:
                    snap, intervention = env.snapshot(), item
            env.step(action)
            trace.append(dict(step=step, player=player, label=label, before=before, after=board(env)))
        if not env.done or env.winner not in (0, 1):
            raise RuntimeError('early-card audit did not reach a decided terminal state')
        result = dict(
            index=index,
            side=side,
            team_0=case.team_0,
            team_1=case.team_1,
            win=int(env.winner == side),
            early=early,
            starting=starting if early else None,
            trace=trace if early else [],
        )
        if probe_step is not None:
            if snap is None:
                raise ValueError('requested early decision not reproduced')
            pairs = []
            for rep in range(repetitions):
                branch_seed = derive_seed(
                    seed, 'early-l6-branch', ((index * 2 + side) * limit + probe_step) * 100 + rep
                )
                pair = {}
                for name, action in [('card', intervention['action']), ('d2', intervention['d2_action'])]:
                    env.restore(snap)
                    env.set_simulation_seed(branch_seed)
                    opponent.rng.seed(branch_seed)
                    env.step(action)
                    for _ in range(limit):
                        if env.done:
                            break
                        env.step((agent if env.acting_player == side else opponent).select_action(env))
                    if not env.done or env.winner not in (0, 1):
                        raise RuntimeError('paired continuation did not terminate')
                    pair[name] = int(env.winner == side)
                pairs.append(pair)
            result['intervention'] = dict(
                **intervention,
                pairs=pairs,
                card_win_rate=float(np.mean([p['card'] for p in pairs])),
                d2_win_rate=float(np.mean([p['d2'] for p in pairs])),
            )
        return result
    finally:
        if snap is not None:
            env.snapshot_free(snap)
        env.close()


def run(config, checkpoint, output, scenarios=240, workers=8, seed=321000):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    cfg = load_cfg(config)
    cases = eval_cases(cfg, seed, scenarios)
    jobs = [(i, side, case, seed, None, 0) for i, case in enumerate(cases) for side in (0, 1)]
    result = dict(
        status='discovering',
        config=config,
        checkpoint=checkpoint,
        checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        provenance=provenance(),
        seed=seed,
        scenarios=scenarios,
        interpretation='Exploratory selected examples, not an unbiased strength estimate. '
        'Replace one early action only; the D2 branch may play that card later.',
    )

    def save():
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / 'result.json')

    save()
    with ProcessPoolExecutor(max_workers=workers, initializer=ev.initialize, initargs=(config, checkpoint, 2)) as pool:
        games = list(pool.map(game, jobs))
        result['games'] = games
        result['counts'] = {
            name: {
                'early_games': sum(any(e['card'] == name for e in g['early']) for g in games),
                'round1_games': sum(any(e['card'] == name and e['round'] == 1 for e in g['early']) for g in games),
                'early_wins': sum(g['win'] and any(e['card'] == name for e in g['early']) for g in games),
                'd2_disagreement_games': sum(
                    any(e['card'] == name and e['d2_disagrees'] for e in g['early']) for g in games
                ),
            }
            for name in CARDS
        }
        result['status'] = 'probing'
        save()
        print(result['counts'], flush=True)
        selected = []
        for name in CARDS:
            candidates = [
                (e['round'], g['index'], g['side'], e['step'])
                for g in games
                if g['win']
                for e in g['early']
                if e['card'] == name and e['d2_disagrees']
            ]
            for _, index, side, step in sorted(candidates)[:3]:
                selected.append((index, side, cases[index], seed, step, 32))
        result['examples'] = list(pool.map(game, selected))
    result['status'] = 'complete'
    save()
    print({'status': 'complete', 'examples': len(result['examples'])}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--scenarios', type=int, default=240)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    run(args.config, args.checkpoint, args.output, args.scenarios, args.workers)
