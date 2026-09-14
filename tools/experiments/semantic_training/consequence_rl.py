"""Matched residual RL followed by held-out selection and independent D2 recheck."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import time

import torch

from tools.experiments.semantic_training import rl
from tools.experiments.semantic_training.compare import compare
from tools.experiments.semantic_training.consequence_policy import FORMAT
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.transfer_probe import run as probe
from tools.rule_validation.verify_panel import verify_variants
from tools.runs._host import load_remote_from_cfg
from training.core.artifact_io import fingerprint, load_checkpoint
from training.core.config.loader import load_cfg


def matched_initials(directory):
    paths = {arm: str(Path(directory) / f'{arm}.pt') for arm in ('candidate', 'control')}
    payloads = {arm: load_checkpoint(path, map_location='cpu', weights_only=False) for arm, path in paths.items()}
    a, b = payloads.values()
    if (
        any(p.get('format') != FORMAT for p in (a, b))
        or a.get('use_consequences') is not True
        or b.get('use_consequences') is not False
    ):
        raise ValueError('explicit matched consequence/control policies required')
    if (
        a['shape'] != b['shape']
        or a.get('parent_sha256') != b.get('parent_sha256')
        or a['net'].keys() != b['net'].keys()
    ):
        raise ValueError('initial policy identities differ')
    if any(not torch.equal(a['net'][key], b['net'][key]) for key in a['net']):
        raise ValueError('initial policy tensors differ')
    if torch.count_nonzero(a['net']['residual.2.weight']):
        raise ValueError('initial residual must be zero')
    return paths


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run on configured training host')
    paths = matched_initials(args.initial)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    source = fingerprint()
    status = dict(status='running', stage='training', settings=vars(args), source_sha256=source, arms={})
    status['tool_sha256'] = {p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))}

    def save():
        status['wall_s'] = time.monotonic() - start
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        temp.replace(root / 'status.json')

    def panel(checkpoint, name, seed, scenarios):
        directory = root / name
        evaluate(
            args.config,
            checkpoint,
            directory,
            scenarios=scenarios,
            layouts=2,
            workers=args.workers,
            seed=seed,
            opponent_depth=2,
            variants=args.catalog,
        )
        report = json.loads((directory / 'result.json').read_text())
        result = verify_variants(
            report,
            load_cfg(args.config),
            args.catalog,
            seed=seed,
            checkpoint_sha256=digest(checkpoint),
            source_sha256=source,
            scenarios=scenarios,
        )
        return dict(checkpoint=checkpoint, **result)

    save()
    try:
        for arm in paths:
            status['arm'] = arm
            save()
            rl.run(
                args.config,
                paths[arm],
                str(root / arm),
                iterations=args.iterations,
                episodes=args.episodes,
                workers=args.workers,
                seed=args.seed,
                dev_seed=args.seed + 90,
                dev_scenarios=55,
                dev_depth=2,
                opponent_depth=2,
                value_baseline=True,
                temperature=0.5,
                variants=args.catalog,
                learning_rate=args.learning_rate,
            )
            report = json.loads((root / arm / 'result.json').read_text())
            if report['status'] != 'complete':
                raise ValueError('incomplete training arm')
            status['arms'][arm] = dict(final=report['checkpoint'])
            save()
        status['stage'] = 'selection'
        save()
        initial_panel = panel(paths['candidate'], 'initial_selection', args.seed + 100, 55)
        probe(args.config, paths['candidate'], root / 'initial_probe.json', device='cuda')
        for arm in paths:
            report = json.loads((root / arm / 'result.json').read_text())
            candidates = [
                initial_panel
                if arm == 'candidate'
                else panel(paths[arm], 'control_initial_selection', args.seed + 100, 55)
            ]
            candidates += [
                panel(item['checkpoint'], f'{arm}_selection_{item["iteration"]}', args.seed + 100, 55)
                for item in report['iterations']
            ]
            selected = max(candidates, key=lambda c: c['score'])['checkpoint']
            status['arms'][arm].update(selected=selected, candidates=candidates)
            probe(args.config, report['checkpoint'], root / f'{arm}_final_probe.json', device='cuda')
            save()
        status['stage'] = 'independent_recheck'
        save()
        status['initial_recheck'] = panel(paths['candidate'], 'initial_recheck', args.seed + 200, 110)
        for arm in paths:
            status['arms'][arm]['recheck'] = panel(
                status['arms'][arm]['selected'], f'{arm}_recheck', args.seed + 200, 110
            )
            compare(
                root / 'initial_recheck/result.json', root / f'{arm}_recheck/result.json', root / f'{arm}_delta.json'
            )
            save()
        compare(root / 'control_recheck/result.json', root / 'candidate_recheck/result.json', root / 'paired.json')
        status.update(status='complete', stage='finished')
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save()
        (root / 'completion.json').write_text(json.dumps(status, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('initial')
    parser.add_argument('output')
    parser.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    parser.add_argument('--iterations', type=int, default=4)
    parser.add_argument('--episodes', type=int, default=512)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--seed', type=int, default=95800)
    parser.add_argument('--learning-rate', type=float, default=1e-5)
    run(parser.parse_args())
