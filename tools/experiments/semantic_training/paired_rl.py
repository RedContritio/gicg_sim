"""RL after paired pretraining: same game budget, with/without continuing consequence replay."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
from functools import partial
import hashlib
import json
from pathlib import Path
import socket
import time
import traceback

import torch

from tools.experiments.semantic_training import rl
from tools.experiments.semantic_training.compare import compare
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.paired_smoke import smoke
from tools.experiments.semantic_training.paired_replay import PairedReplay, prepare_initial, retention, validate_resume
from tools.experiments.semantic_training.rl_update import update
from tools.rule_validation.verify_panel import verify_variants
from tools.runs._host import load_remote_from_cfg
from training.core.artifact_io import fingerprint, load_checkpoint
from training.core.config.loader import load_cfg


def _resume_paths(value):
    if value is None:
        return {}
    if '{arm}' in value:
        paths = {arm: Path(value.format(arm=arm)) for arm in ('auxiliary', 'control')}
    else:
        root = Path(value)
        if not root.is_dir():
            raise ValueError('resume must be a run directory or a path template containing {arm}')
        paths = {arm: root / arm / 'ckpts/latest.pt' for arm in ('auxiliary', 'control')}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f'resume checkpoints are missing: {missing}')
    return paths


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run on configured remote host')
    if args.smoke and (args.resume or args.resume_initial):
        raise ValueError('smoke and resume are mutually exclusive')
    if args.resume_initial and not args.resume:
        raise ValueError('resume initial requires a resume checkpoint')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    resume_paths = _resume_paths(args.resume)
    tick = time.monotonic()
    status = dict(
        status='running',
        stage='initializing',
        iterations=args.iterations,
        episodes=args.episodes,
        workers=args.workers,
        training_seed=args.seed,
        selection_seed=95200,
        recheck_seed=95300,
        source_sha256=fingerprint(),
        config=args.config,
        catalog=args.catalog,
        arms={},
        checkpoint=args.checkpoint,
        pairs=args.pairs,
        resume={arm: str(path) for arm, path in resume_paths.items()},
        resume_initial=args.resume_initial,
        scope='development RL comparison, not final acceptance',
    )
    inputs = [args.config, args.catalog, args.checkpoint, args.pairs]
    inputs.extend(str(path) for path in resume_paths.values())
    if args.resume_initial:
        inputs.append(args.resume_initial)
    status['input_sha256'] = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in inputs}
    status['tool_sha256'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))
    }

    def save():
        status['wall_s'] = time.monotonic() - tick
        tmp = root / 'status.tmp'
        tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(root / 'status.json')

    def panel(checkpoint, name, seed, scenarios):
        status['panel'] = name
        save()
        out = root / name
        evaluate(
            args.config,
            str(checkpoint),
            out,
            scenarios=scenarios,
            layouts=2,
            workers=args.workers,
            seed=seed,
            opponent_depth=2,
            variants=args.catalog,
        )
        report = json.loads((out / 'result.json').read_text())
        verified = verify_variants(
            report,
            load_cfg(args.config),
            args.catalog,
            seed=seed,
            scenarios=scenarios,
            checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
            source_sha256=fingerprint(),
        )
        return dict(checkpoint=str(checkpoint), **verified)

    save()
    with (root / 'console.log').open('w', encoding='utf-8', buffering=1) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                torch.set_num_threads(1)
                initial = root / 'initial.pt'
                payload = prepare_initial(args.checkpoint, initial, resume_initial=args.resume_initial)
                pairs = torch.load(args.pairs, weights_only=False)
                if args.smoke:
                    status.update(smoke(args, root, initial, payload, pairs))
                else:
                    for arm, beta in (('auxiliary', 0.5), ('control', 0.0)):
                        replay = PairedReplay(pairs, args.seed + 3)
                        resume = resume_paths.get(arm)
                        if resume is not None:
                            resume_payload = load_checkpoint(resume, map_location='cpu', weights_only=False)
                            resume_protocol = validate_resume(
                                resume_payload,
                                anchor_sha256=hashlib.sha256(initial.read_bytes()).hexdigest(),
                                pair_sha256=status['input_sha256'][args.pairs],
                                expected_beta=beta,
                            )
                            replay.rng.setstate(resume_protocol['rng'])
                            replay.calls = resume_protocol['calls']
                        status.update(stage='rl', arm=arm)
                        status['arms'][arm] = dict(beta=beta, pair_batch=8, difference_beta=1.0)
                        save()
                        original_update = rl.update
                        original_save = rl.save_checkpoint
                        rl.update = partial(update, auxiliary_loss=replay)

                        def save_replay_checkpoint(model, path):
                            model = dict(model)
                            model['algorithm'] += ' paired-replay protocol 1.0.0'
                            model['paired_replay'] = dict(
                                beta=beta,
                                path=args.pairs,
                                sha256=status['input_sha256'][args.pairs],
                                rng=replay.rng.getstate(),
                                calls=replay.calls,
                                batch_pairs=8,
                                difference_beta=1.0,
                                scope='train split only',
                            )
                            original_save(model, path)

                        rl.save_checkpoint = save_replay_checkpoint
                        try:
                            rl.run(
                                args.config,
                                str(initial),
                                str(root / arm),
                                iterations=args.iterations,
                                episodes=args.episodes,
                                workers=args.workers,
                                seed=args.seed,
                                dev_seed=95190,
                                dev_scenarios=55,
                                dev_depth=2,
                                opponent_depth=2,
                                value_baseline=True,
                                temperature=0.5,
                                variants=args.catalog,
                                rule_beta=beta,
                                rule_stride=1000000000,
                                evaluate_dev=False,
                                resume=resume,
                                resume_algorithm_suffix=' paired-replay protocol 1.0.0',
                            )
                        finally:
                            rl.update = original_update
                            rl.save_checkpoint = original_save
                        report = json.loads((root / arm / 'result.json').read_text())
                        if report['status'] != 'complete':
                            raise ValueError('incomplete RL arm')
                        status['arms'][arm].update(
                            replay_calls=replay.calls,
                            final=report['checkpoint'],
                            replay_rng=repr(replay.rng.getstate()),
                        )
                        save()
                    if args.evaluate:
                        status.update(stage='variant_selection')
                        initial_panel = panel(initial, 'dev_0', 95200, 55)
                        status['initial_retention'] = retention(initial, payload, pairs)
                        for arm in ('auxiliary', 'control'):
                            report = json.loads((root / arm / 'result.json').read_text())
                            candidates = [initial_panel]
                            for item in report['iterations']:
                                candidates.append(
                                    panel(item['checkpoint'], f'{arm}_dev_{item["iteration"]}', 95200, 55)
                                )
                            selected = max(candidates, key=lambda x: x['score'])['checkpoint']
                            status['arms'][arm].update(
                                candidates=candidates,
                                selected=selected,
                                retention=retention(selected, payload, pairs),
                                final_retention=retention(report['checkpoint'], payload, pairs),
                            )
                            save()
                        status.update(stage='independent_development_recheck')
                        status['baseline_recheck'] = panel(initial, 'baseline_recheck', 95300, 110)
                        for arm in ('auxiliary', 'control'):
                            status['arms'][arm]['recheck'] = panel(
                                status['arms'][arm]['selected'], f'{arm}_recheck', 95300, 110
                            )
                            compare(
                                root / 'baseline_recheck/result.json',
                                root / f'{arm}_recheck/result.json',
                                root / f'{arm}_vs_baseline.json',
                            )
                        compare(
                            root / 'control_recheck/result.json',
                            root / 'auxiliary_recheck/result.json',
                            root / 'paired.json',
                        )
                status.update(status='complete', stage='finished')
        except BaseException as error:
            traceback.print_exc(file=log)
            status.update(status='failed', error=repr(error))
            raise
        finally:
            save()
            (root / 'completion.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: status[k] for k in ('status', 'wall_s')}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('pairs')
    p.add_argument('output')
    p.add_argument('--resume')
    p.add_argument('--resume-initial')
    p.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    p.add_argument('--iterations', type=int, default=4)
    p.add_argument('--episodes', type=int, default=512)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=95100)
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--evaluate', action='store_true')
    run(p.parse_args())
