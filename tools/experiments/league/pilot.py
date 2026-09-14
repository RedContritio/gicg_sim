"""One bounded league expansion: main learner, exploiter and paired payoff matrix."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from itertools import combinations
from tools.experiments.league.pool import pfsp
from tools.experiments.league.run import digest
from training.core.artifact_io import fingerprint


def call(module, args, log):
    with Path(log).open('w', encoding='utf-8') as stream:
        subprocess.run(
            [sys.executable, '-X', 'utf8', '-u', '-m', module, *map(str, args)],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
        )


def pilot(config, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    state = {'status': 'preparing', 'source': fingerprint(), 'budget_per_role': 6000}

    def save():
        path = output / 'execution.json'
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)

    save()
    root = Path('artifacts/remote_resume_v17')
    members = [
        {'id': f's{s}_{f}', 'checkpoint': str(root / f's{s}_{f}.pt')}
        for s, f in [(41, 20000), (42, 12000), (43, 20000), (43, 30000)]
    ]
    try:
        for member in members:
            member['sha256'] = digest(member['checkpoint'])
        initial = members[2]
        scores = []
        state['status'] = 'initial_matchmaking'
        save()
        for member in members:
            if member == initial:
                scores.append(0.5)
                continue
            path = output / f'initial_vs_{member["id"]}.json'
            call(
                'tools.experiments.evaluate_history',
                [config, initial['checkpoint'], member['checkpoint'], path, '--seed', 115000, '--scenarios', 16],
                path.with_suffix('.log'),
            )
            scores.append(json.loads(path.read_text())['score'])
        weights = pfsp(scores)
        plan = {
            'schema': 1,
            'project_version': 'v0.2.0',
            'source': fingerprint(),
            'config': str(config),
            'device': 'cuda',
            'output': str(output),
            'budget': 6000,
            'members': members,
            'matchmaking_seed': 115000,
            'evaluation_seed': 116000,
            'initial_scores': scores,
            'tool_sha256': {p.as_posix(): digest(p) for p in sorted(Path('tools/experiments/league').glob('*.py'))},
            'roles': {
                'main': {
                    'seed': 51,
                    'epsilon': 0.2,
                    'initial': initial['id'],
                    'opponents': [{'id': 'random', 'weight': 0.2}, {'id': 'F1-D2', 'weight': 0.2}]
                    + [{'id': m['id'], 'weight': 0.6 * w} for m, w in zip(members, weights)],
                },
                'exploiter': {
                    'seed': 52,
                    'epsilon': 0.3,
                    'initial': initial['id'],
                    'opponents': [{'id': initial['id'], 'weight': 1.0}],
                },
            },
        }
        path = output / 'plan.json'
        path.write_text(json.dumps(plan, indent=2))
        state.update(status='training', plan=str(path))
        save()

        def learn(role):
            call('tools.experiments.league.run', [path, role], output / f'{role}.log')

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(learn, ('main', 'exploiter')))
        candidates = []
        for role in ('main', 'exploiter'):
            record = json.loads((output / f'{role}.json').read_text())
            assert record['status'] == 'complete'
            candidates.append({'id': role, 'checkpoint': record['checkpoint'], 'sha256': record['sha256']})
        members += candidates
        state.update(status='evaluating', members=members)
        save()
        jobs = []
        for a, b in combinations(members, 2):
            path = output / f'pair_{a["id"]}_{b["id"]}.json'
            jobs.append(
                (
                    'tools.experiments.evaluate_history',
                    [config, a['checkpoint'], b['checkpoint'], path, '--seed', 116000, '--scenarios', 32],
                    path,
                )
            )
        for member in [initial, *candidates]:
            path = output / f'ladder_{member["id"]}.json'
            jobs.append(
                (
                    'tools.experiments.evaluate_clean',
                    [config, member['checkpoint'], path, '--seed', 116000, '--scenarios', 32],
                    path,
                )
            )

        def evaluate(job):
            module, args, path = job
            call(module, args, path.with_suffix('.log'))

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(evaluate, jobs))
        from tools.experiments.league.report import summarize

        report = summarize(output, members)
        state.update(status='complete', report=str(output / 'report.md'), results=report)
        save()
    except BaseException as error:
        state.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('output')
    args = parser.parse_args()
    pilot(args.config, args.output)
