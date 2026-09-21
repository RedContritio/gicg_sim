"""Retention-arm comparison: does rule supervision have to destroy the policy?

The harm isolated: ``paired_training.run`` optimised every parameter of the policy network
and the rule head under a pure consequence-regression loss, and an imitation-warm-started
policy fell from 34.55% to 19.09% on the same 440-game panel. Arms differ only in the
preservation mechanism -- checkpoint, data, step budget and seed are shared. Mechanism
evidence (cosine, CKA, drift) is reported alongside the paired panel but never replaces it.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import socket
import time

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.compare import compare
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.paired_lessons import build_pair, tasks
from tools.experiments.semantic_training.paired_replay import export_initial
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.experiments.semantic_training.representation_drift import linear_cka, model_digest, tensor_drift
from tools.experiments.semantic_training.retention_arms import arm_specs, run_arm
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.transfer_probe import run as probe
from tools.rule_validation.verify_panel import verify_variants
from tools.runs import schema
from tools.runs._host import load_remote_from_cfg
from tools.runs._train.setup import phase_a_setup
from tools.runs._train.snapshot import phase_b_write_cfg_metadata
from tools.runs.helpers import write_metadata_atomic
from training.core.artifact_io import fingerprint, load_checkpoint, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def initialize_rule_head(agent, seed):
    torch.manual_seed(seed)
    return attach(agent)


def pooled_states(net, cfg, device, observations):
    """Pooled per-state representation used for CKA (the only surface ``forward`` exposes)."""
    batch = batch_observations(observations, cfg, device)
    with torch.no_grad():
        _, state, _ = net(batch, return_actions=True)
    return state


def build_pairs(config, catalog, shape, seed, contexts, workers):
    jobs = tasks(config, catalog, shape, seed, contexts)
    if not jobs:
        raise ValueError('no paired tasks for this config and catalog')
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(build_pair, jobs, chunksize=1))


def load_teacher_rows(directory, limit, seed):
    paths = sorted(Path(directory).glob('episode_*.pt'))
    if not paths:
        raise FileNotFoundError(f'no teacher episodes under {directory}')
    rows = [row for path in paths for row in torch.load(path, weights_only=False)['rows']]
    if not rows:
        raise ValueError('teacher episodes contain no decision rows')
    missing = [index for index, row in enumerate(rows) if not row.get('tied')]
    if missing:
        raise ValueError(f'teacher rows without tied expert sets at {missing[:3]}')
    if limit and len(rows) > limit:
        rows = random.Random(seed).sample(rows, limit)
    return rows


def train_arm(warmup, spec, pairs, rows, output, *, device, steps, seed, diag_every, cos_momentum):
    observations = [row['obs'] for pair in pairs[:16] for row in pair['rows']]
    reference = SemanticAgent(AgentConfig(**warmup['shape']), device)
    reference.net.load_state_dict(warmup['net'], strict=True)
    reference.net.eval()
    reference_states = pooled_states(reference.net, reference.cfg, device, observations).cpu()

    agent = SemanticAgent(AgentConfig(**warmup['shape']), device)
    agent.net.load_state_dict(warmup['net'], strict=True)
    initialize_rule_head(agent, seed)
    if 'rule_head' in warmup:
        agent.rule_head.load_state_dict(warmup['rule_head'], strict=True)
    initial_digest = model_digest(agent)
    _, report = run_arm(
        agent, spec, pairs, rows, steps=steps, seed=seed, diag_every=diag_every, cos_momentum=cos_momentum
    )
    report['initial_digest'] = initial_digest
    report['net_drift'] = tensor_drift(warmup['net'], agent.net.state_dict())
    report['cka'] = linear_cka(reference_states, pooled_states(agent.net, agent.cfg, device, observations).cpu())
    diagnostic = output / f'{spec.name}.pt'
    payload = dict(
        format='paired-consequence/1.0.0',
        parent_format=FORMAT,
        shape=warmup['shape'],
        net=agent.net.state_dict(),
        rule_head=agent.rule_head.state_dict(),
        arm=spec.name,
        settings={'temperature': 0.5},
    )
    if hasattr(agent, 'rule_adapter'):
        payload['rule_adapter'] = agent.rule_adapter.state_dict()
    save_checkpoint(
        payload,
        diagnostic,
    )
    policy = output / f'{spec.name}_policy.pt'
    export_initial(diagnostic, policy)
    report.update(checkpoint=str(diagnostic), policy_checkpoint=str(policy))
    return report


def panel(config, checkpoint, directory, *, scenarios, layouts, workers, seed, catalog):
    evaluate(
        config,
        checkpoint,
        directory,
        scenarios=scenarios,
        layouts=layouts,
        workers=workers,
        seed=seed,
        opponent_depth=2,
        variants=catalog,
    )
    report = json.loads((directory / 'result.json').read_text())
    return verify_variants(
        report,
        load_cfg(config),
        catalog,
        seed=seed,
        checkpoint_sha256=digest(checkpoint),
        source_sha256=fingerprint(),
        scenarios=scenarios,
    )


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is not None and socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run on the configured training host, or set [meta].host = "local"')
    warmup = load_checkpoint(args.warmup, map_location='cpu', weights_only=False)
    if warmup.get('format') != FORMAT:
        raise ValueError(f'warmup must be {FORMAT}, got {warmup.get("format")!r}')
    specs = arm_specs(replay_lambda=args.replay_lambda, anchor_beta=args.anchor_beta)
    selected = args.arms.split(',') if args.arms else list(specs)
    unknown = [name for name in selected if name not in specs]
    if unknown:
        raise ValueError(f'unknown arms {unknown}; available {sorted(specs)}')
    # The gradient-cosine diagnostic measures at step 1 / every diag_every / final
    # step for EVERY arm (run_arm), so the D2-imitation teacher rows are always
    # required as the main-task proxy — even for mechanism-free arms such as
    # `full` run alone.
    needs_teacher = bool(selected)

    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    status = dict(
        status='running',
        settings=vars(args),
        source_sha256=fingerprint(),
        warmup=args.warmup,
        warmup_sha256=digest(args.warmup),
        arms=selected,
        scope='controlled retention comparison, not a strength claim',
    )
    status['tool_sha256'] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.glob('*.py'))
    }

    def save(complete=False):
        status['wall_s'] = time.monotonic() - start
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / ('completion.json' if complete else 'status.json'))

    save()
    try:
        if args.pairs:
            pairs = torch.load(args.pairs, weights_only=False)
            status['pairs_source'] = args.pairs
        else:
            pairs = build_pairs(args.config, args.catalog, warmup['shape'], args.seed, args.contexts, args.workers)
            torch.save(pairs, root / 'pairs.pt')
        status['pairs_total'] = len(pairs)
        rows = load_teacher_rows(args.teacher, args.teacher_rows, args.seed) if needs_teacher else []
        status.update(teacher_rows=len(rows), stage='arms')
        save()

        arm_kwargs = dict(
            device=args.device,
            steps=args.steps,
            seed=args.seed,
            diag_every=args.diag_every,
            cos_momentum=args.cos_momentum,
        )
        initial = None
        initial_digest = None
        for name in selected:
            arm_start = time.monotonic()
            directory = open_arm_dir(args.config, name)
            try:
                report = train_arm(warmup, specs[name], pairs, rows, directory, **arm_kwargs)
                close_arm_dir(directory, arm_start, True, f'retention arm {name}')
            except BaseException as error:
                close_arm_dir(directory, arm_start, False, f'retention arm {name}: {error!r}')
                raise
            if initial is None:
                initial = report['initial']
                initial_digest = report['initial_digest']
            elif report['initial_digest'] != initial_digest:
                raise ValueError(f'retention arm {name} does not start from the shared initial state')
            (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            status.setdefault('results', {})[name] = report
            save()
            print(
                f'{name}: cka={report["cka"]:.4f} drift_max={report["net_drift"]["max"]:.4g} '
                f'cos_ema={report["cos_ema_final"]} blocks={report["gate_blocks"]}',
                flush=True,
            )

        if args.panel_scenarios:
            status['stage'] = 'panels'
            panel_kwargs = dict(
                scenarios=args.panel_scenarios,
                layouts=args.layouts,
                workers=args.workers,
                seed=args.panel_seed,
                catalog=args.catalog,
            )
            status['warmup_panel'] = panel(args.config, args.warmup, root / 'warmup_panel', **panel_kwargs)
            for name in selected:
                checkpoint = status['results'][name]['policy_checkpoint']
                destination = root / f'{name}_panel'
                status['results'][name]['panel'] = panel(args.config, checkpoint, destination, **panel_kwargs)
                compare(
                    root / 'warmup_panel' / 'result.json',
                    destination / 'result.json',
                    root / f'{name}_delta.json',
                )
                if args.probe:
                    probe(args.config, checkpoint, root / f'{name}_probe.json', device=args.device)
                save()
        status.update(status='complete', stage='finished')
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save(complete=True)


def open_arm_dir(config, arm):
    state = phase_a_setup(argparse.Namespace(cfg=config, override=[f'meta.run_label=retention_{arm}']))
    phase_b_write_cfg_metadata(state, Path(config))
    return state.artifacts_dir


def close_arm_dir(directory, start, ok, notes):
    meta = schema.load_file(directory / 'metadata.toml')
    meta.status = 'done' if ok else 'failed'
    meta.wall_seconds = time.monotonic() - start
    meta.exit_code = 0 if ok else 1
    meta.notes = notes
    write_metadata_atomic(directory, meta)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('warmup')
    parser.add_argument('output')
    parser.add_argument('--teacher', required=True, help='directory holding the warmup teacher episodes')
    parser.add_argument('--arms', default=None, help='comma-separated subset; default all configured arms')
    parser.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    parser.add_argument('--pairs', default=None, help='reuse an existing pairs.pt instead of rebuilding')
    parser.add_argument('--steps', type=int, default=1500)
    parser.add_argument('--contexts', type=int, default=6)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--teacher-rows', type=int, default=2048)
    parser.add_argument('--seed', type=int, default=95000)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--diag-every', type=int, default=50)
    parser.add_argument('--cos-momentum', type=float, default=0.9)
    parser.add_argument('--replay-lambda', type=float, default=1.0)
    parser.add_argument('--anchor-beta', type=float, default=1.0)
    parser.add_argument('--panel-scenarios', type=int, default=0, help='0 skips the evaluation panels')
    parser.add_argument('--layouts', type=int, default=2)
    parser.add_argument('--panel-seed', type=int, default=96500)
    parser.add_argument('--probe', action='store_true', help='also run the Kaeya decision probe per arm')
    run(parser.parse_args())
