"""RL after paired pretraining: same game budget, with/without continuing consequence replay."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from functools import partial
import hashlib
import json
from pathlib import Path
import random
import socket
import time
import traceback

import torch

from tools.experiments.semantic_training import rl
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.compare import compare
from tools.experiments.semantic_training.evaluate import evaluate, initialize
from tools.experiments.semantic_training.paired_replay import PairedReplay, export_initial, retention
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import update
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.value_baseline import attach as attach_value
from tools.rule_validation.verify_panel import verify_variants
from tools.runs._host import load_remote_from_cfg
from training.core.artifact_io import fingerprint, load_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig


def smoke(args, root, initial, payload, pairs):
    directory = root / 'rollouts'
    directory.mkdir()
    with ProcessPoolExecutor(max_workers=4, initializer=initialize, initargs=(args.config, str(initial), 2)) as pool:
        records = list(pool.map(episode, [(1, i, str(directory), args.seed, args.catalog, 0) for i in range(4)]))
    rows = [row for record in records for row in torch.load(record['path'], weights_only=False)]
    results = {}
    for arm, beta in (('auxiliary', 0.5), ('control', 0.0)):
        torch.manual_seed(args.seed)
        shape = AgentConfig(**payload['shape'])
        agent, anchor = SemanticAgent(shape, 'cuda'), SemanticAgent(shape, 'cuda')
        for model in (agent, anchor):
            model.net.load_state_dict(payload['net'])
        anchor.net.requires_grad_(False)
        optimizer = torch.optim.AdamW(agent.net.parameters(), lr=1e-5, weight_decay=0)
        value_optimizer = torch.optim.AdamW(attach_value(agent).parameters(), lr=0.0003)
        rule_optimizer = torch.optim.AdamW(attach(agent).parameters(), lr=0.0003) if beta else None
        if beta:
            agent.rule_head.load_state_dict(payload['rule_head'])
        replay = PairedReplay(pairs, args.seed + 3)
        results[arm] = update(
            agent,
            anchor,
            optimizer,
            rows[:64],
            [0, 0],
            random.Random(args.seed + 2),
            epochs=1,
            value_optimizer=value_optimizer,
            temperature=0.5,
            rule_optimizer=rule_optimizer,
            rule_beta=beta,
            auxiliary_loss=replay,
        )
        if results[arm]['updates'] < 1:
            raise ValueError('smoke performed no optimizer update')
        results[arm]['replay_calls'] = replay.calls
    return dict(scope='four real games and both update paths; not strength evaluation', results=results)


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run on configured remote host')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
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
        scope='development RL comparison, not final acceptance',
    )
    status['input_sha256'] = {
        p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (args.config, args.catalog, args.checkpoint, args.pairs)
    }
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
                payload = export_initial(args.checkpoint, initial)
                pairs = torch.load(args.pairs, weights_only=False)
                if args.smoke:
                    status.update(smoke(args, root, initial, payload, pairs))
                else:
                    for arm, beta in (('auxiliary', 0.5), ('control', 0.0)):
                        replay = PairedReplay(pairs, args.seed + 3)
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
                    # Start actual training first; all selection and independent panels follow.
                    status.update(stage='variant_selection')
                    initial_panel = panel(initial, 'dev_0', 95200, 55)
                    status['initial_retention'] = retention(initial, payload, pairs)
                    for arm in ('auxiliary', 'control'):
                        report = json.loads((root / arm / 'result.json').read_text())
                        candidates = [initial_panel]
                        for item in report['iterations']:
                            candidates.append(panel(item['checkpoint'], f'{arm}_dev_{item["iteration"]}', 95200, 55))
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
    p.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    p.add_argument('--iterations', type=int, default=4)
    p.add_argument('--episodes', type=int, default=512)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=95100)
    p.add_argument('--smoke', action='store_true')
    run(p.parse_args())
