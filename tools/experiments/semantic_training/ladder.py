"""Frozen BC/RL five-opponent panel over three fresh 2v2 scenario seeds."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from tools.experiments.eval_ladder import BASELINES, make_baseline, evaluation_provenance
from tools.experiments.skill_abuser import load_skill_catalog
from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.teams import eval_cases, with_teams, matchup_key
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed

_CATALOG = None


def initialize(config, checkpoint, catalog):
    global _CATALOG
    _CATALOG = catalog
    ev.initialize(config, checkpoint)


def game(job):
    baseline, seed, index, side, layout, case = job
    cfg = with_teams(ev._CFG, case.team_0, case.team_1)
    env = make_env_factory(cfg, None, seed)(index, layout_seed=derive_seed(seed, 'layout', index * 100 + layout))
    opponent = make_baseline(baseline, derive_seed(seed, 'opponent', index * 2 + side), _CATALOG)
    action_counts = defaultdict(int)
    ends_with_skill = 0
    try:
        env.reset(seed=case.env_seed, deck_seeds=(case.deck_seed_p0, case.deck_seed_p1))
        ev._AGENT.game_start(env.static_obs)
        for step in range(cfg.paradigm['max_game_steps']):
            if env.done:
                break
            own = env.acting_player == side
            action = (ev._AGENT if own else opponent).select_action(env)
            if own:
                kinds, _ = env.get_legal_actions()
                action_counts[str(int(kinds[action]))] += 1
                ends_with_skill += int(kinds[action] == 3 and (kinds == 0).any())
            env.step(action)
        if not env.done or env.winner not in (0, 1):
            raise RuntimeError('panel game did not reach a decided terminal state')
        view = env.export_view()
        return dict(
            baseline=baseline,
            seed=seed,
            index=index,
            side=side,
            layout=layout,
            team_0=case.team_0,
            team_1=case.team_1,
            matchup=matchup_key(case.team_0, case.team_1),
            action_counts=dict(action_counts),
            ends_with_skill=ends_with_skill,
            win=int(env.winner == side),
            steps=step,
            final_round=view['round'],
            timeout=view['round'] >= 10 and all(p['alive_count'] > 0 for p in view['players']),
        )
    finally:
        env.close()


def summarize(rows):
    result = {}
    for baseline in BASELINES:
        games = [r for r in rows if r['baseline'] == baseline]
        groups = defaultdict(list)
        for r in games:
            groups[(r['seed'], r['index'])].append(r['win'])
        clustered = np.array([np.mean(v) for v in groups.values()])
        rng = np.random.default_rng(147100)
        boot = clustered[rng.integers(len(clustered), size=(10000, len(clustered)))].mean(axis=1)
        result[baseline] = dict(
            score=float(clustered.mean()),
            ci95=np.quantile(boot, [0.025, 0.975]).tolist(),
            games=len(games),
            scenarios=len(groups),
            per_seed={
                str(s): float(np.mean([g['win'] for g in games if g['seed'] == s]))
                for s in sorted({g['seed'] for g in games})
            },
            per_matchup={
                m: float(np.mean([g['win'] for g in games if g['matchup'] == m]))
                for m in sorted({g['matchup'] for g in games})
            },
            per_side={str(side): float(np.mean([g['win'] for g in games if g['side'] == side])) for side in (0, 1)},
            per_layout={
                str(layout): float(np.mean([g['win'] for g in games if g['layout'] == layout])) for layout in (0, 1)
            },
            per_own_team={
                team: float(np.mean([g['win'] for g in games if '+'.join(sorted(g['team_' + str(g['side'])])) == team]))
                for team in sorted({'+'.join(sorted(g['team_' + str(g['side'])])) for g in games})
            },
            mean_steps=float(np.mean([g['steps'] for g in games])),
            ends_with_skill=sum(g['ends_with_skill'] for g in games),
            timeout_games=sum(g['timeout'] for g in games),
            timeout_wins=sum(g['timeout'] and g['win'] for g in games),
        )
    return result


def run(config, anchor, candidate, output, workers=20):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    cfg = load_cfg(config)
    roster = cfg.scenario.char_pool
    catalog = load_skill_catalog(with_teams(cfg, roster[:3], roster[3:]))
    jobs = [
        (baseline, seed, i, side, layout, case)
        for baseline in BASELINES
        for seed in (147000, 148000, 149000)
        for i, case in enumerate(eval_cases(cfg, seed, 120))
        for side in (0, 1)
        for layout in (0, 1)
    ]
    start = time.monotonic()
    status = dict(
        status='running',
        provenance=provenance(),
        opponents=evaluation_provenance(),
        scenario_seeds=[147000, 148000, 149000],
        scenarios_per_seed=120,
        layouts=2,
        workers=workers,
        panels={},
    )

    def save():
        status['wall_s'] = time.monotonic() - start
        (root / 'result.tmp').write_text(json.dumps(status, indent=2), encoding='utf-8')
        (root / 'result.tmp').replace(root / 'result.json')

    save()
    try:
        for name, path in [('bc', anchor), ('rl', candidate)]:
            rows = []
            status['active_panel'] = name
            status['games_done'] = 0
            save()
            with (root / f'{name}.jsonl').open('x', encoding='utf-8') as stream:
                with ProcessPoolExecutor(
                    max_workers=workers, initializer=initialize, initargs=(config, path, catalog)
                ) as pool:
                    for row in pool.map(game, jobs):
                        rows.append(row)
                        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                        if len(rows) % 240 == 0:
                            stream.flush()
                            status['games_done'] = len(rows)
                            save()
                            print(name, len(rows), flush=True)
            status['panels'][name] = dict(
                checkpoint=path, sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(), results=summarize(rows)
            )
            save()
        status['status'] = 'complete'
        save()
        print(status, flush=True)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('anchor')
    p.add_argument('candidate')
    p.add_argument('output')
    p.add_argument('--workers', type=int, default=20)
    a = p.parse_args()
    run(a.config, a.anchor, a.candidate, a.output, a.workers)
