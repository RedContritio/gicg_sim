"""Registered semantic policy warm-up; full-game D2 demonstrations, GPU updates."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random
import time

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.data import teacher_episode
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.runs._train.setup import phase_a_setup
from tools.runs._train.snapshot import phase_b_write_cfg_metadata
from tools.runs.helpers import write_metadata_atomic
from tools.runs import schema
from training.core.artifact_io import provenance, save_checkpoint, load_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def run(
    config,
    output,
    episodes=128,
    steps=2000,
    workers=8,
    seed=123000,
    initial=None,
    variants=None,
    learner=None,
    replay_dirs=(),
    learning_rate=0.0003,
    tie_objective='uniform',
    anchor_beta=0.0,
):
    if learning_rate <= 0 or tie_objective not in ('uniform', 'set') or anchor_beta < 0:
        raise ValueError('invalid supervised update settings')
    if anchor_beta and not initial:
        raise ValueError('anchored updates require an initial checkpoint')
    if variants and episodes % 4:
        raise ValueError('variant mixture requires episodes divisible by four')
    from tools.rule_validation.variants import specification

    variant_identity = specification(variants)[1] if variants else None
    start = time.monotonic()
    control = Path(output)
    control.mkdir(parents=True, exist_ok=False)
    state = phase_a_setup(argparse.Namespace(cfg=config, override=['meta.run_label=semantic_warmup']))
    phase_b_write_cfg_metadata(state, Path(config))
    root = state.artifacts_dir
    data = root / 'teacher'
    data.mkdir()
    (data / 'provenance.json').write_text(json.dumps(provenance()), encoding='utf-8')
    status = {
        'status': 'collecting',
        'run': str(root),
        'episodes': episodes,
        'steps': steps,
        'workers': workers,
        'seed': seed,
        'initial': initial,
        'learner': learner,
        'replay_dirs': list(replay_dirs),
        'variants': variants,
        'variant_specification_sha256': variant_identity,
        'algorithm': 'D2 DAgger aggregation' if learner else 'D2 soft-tie imitation warm-up',
        'learning_rate': learning_rate,
        'tie_objective': tie_objective,
        'anchor_beta': anchor_beta,
        'provenance': provenance(),
    }

    def save():
        tmp = control / 'result.tmp'
        tmp.write_text(json.dumps(status, indent=2))
        tmp.replace(control / 'result.json')

    def close(ok):
        meta = schema.load_file(root / 'metadata.toml')
        meta.status = 'done' if ok else 'failed'
        meta.wall_seconds = time.monotonic() - start
        meta.exit_code = 0 if ok else 1
        meta.notes = status['algorithm']
        write_metadata_atomic(root, meta)

    save()
    try:
        jobs = [(config, i, str(data), seed, variants, learner) for i in range(episodes)]
        records = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for record in pool.map(teacher_episode, jobs):
                records.append(record)
                if len(records) % 16 == 0:
                    status['episodes_done'] = len(records)
                    save()
                    print(status['episodes_done'], flush=True)
        (root / 'episodes.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        torch.set_num_threads(1)
        torch.manual_seed(seed + 1)
        cfg = load_cfg(config)
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape, device='cuda')
        if initial:
            payload = load_checkpoint(initial, map_location='cpu', weights_only=False)
            agent.net.load_state_dict(payload['net'])
        anchor = None
        if anchor_beta:
            from copy import deepcopy

            anchor = deepcopy(agent.net).eval().requires_grad_(False)
        rows = [row for record in records for row in torch.load(record['path'], weights_only=False)['rows']]
        from training.core.artifact_io import validate

        replay = []
        for directory in replay_dirs:
            directory = Path(directory)
            validate(json.loads((directory / 'provenance.json').read_text()))
            replay.extend(
                row for p in sorted(directory.glob('episode_*.pt')) for row in torch.load(p, weights_only=False)['rows']
            )
        status.update(
            replay_rows=len(replay),
            learner_decisions=sum(r['learner_decisions'] for r in records),
            expert_disagreements=sum(r['expert_disagreements'] for r in records),
        )
        optimizer = torch.optim.AdamW(
            [p for p in agent.net.parameters() if p.requires_grad], lr=learning_rate, weight_decay=0
        )
        rng = random.Random(seed + 2)
        from collections import Counter

        coverage = Counter()
        for record in records:
            coverage.update(record.get('deck_counts', {}))
        status.update(status='training', rows=len(rows), deck_counts=dict(coverage))
        save()
        (root / 'ckpts').mkdir(exist_ok=True)
        for step in range(1, steps + 1):
            selected = rng.choices(rows, k=16) + rng.choices(replay, k=16) if replay else rng.choices(rows, k=32)
            batch = batch_observations([r['obs'] for r in selected], shape, 'cuda')
            logits = agent.net(batch).masked_fill(~batch['legal_mask'], -1e9)
            from tools.experiments.semantic_training.imitation_loss import imitation_loss

            with torch.no_grad():
                old = anchor(batch).masked_fill(~batch['legal_mask'], -1e9) if anchor is not None else None
            loss, fit, kl = imitation_loss(logits, [r['tied'] for r in selected], tie_objective, old, anchor_beta)
            if not torch.isfinite(loss):
                raise ValueError('nonfinite warm-up loss')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 5)
            optimizer.step()
            if step % 100 == 0 or step == steps:
                status.update(
                    step=step,
                    loss=float(loss.detach()),
                    fit=float(fit),
                    anchor_kl=float(kl),
                    wall_s=time.monotonic() - start,
                )
                save()
                print({k: status[k] for k in ('step', 'loss', 'wall_s')}, flush=True)
            if step % 500 == 0 or step == steps:
                payload = {
                    'format': FORMAT,
                    'net': agent.net.state_dict(),
                    'optimizer': optimizer.state_dict(),
                    'step': step,
                    'rng': rng.getstate(),
                    'torch_rng': torch.get_rng_state(),
                    'cuda_rng': torch.cuda.get_rng_state_all(),
                    'shape': vars(shape),
                    'algorithm': status['algorithm'],
                    'learning_rate': learning_rate,
                    'tie_objective': tie_objective,
                    'anchor_beta': anchor_beta,
                    'anchor_checkpoint': initial if anchor_beta else None,
                    'variant_specification_sha256': variant_identity,
                }
                save_checkpoint(payload, root / 'ckpts' / f'step_{step}.pt')
                save_checkpoint(payload, root / 'ckpts/latest.pt')
        status.update(status='complete', checkpoint=str(root / 'ckpts/latest.pt'))
        save()
        close(True)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        close(False)
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--episodes', type=int, default=128)
    p.add_argument('--steps', type=int, default=2000)
    p.add_argument('--workers', type=int, default=8)
    a = p.parse_args()
    run(a.config, a.output, a.episodes, a.steps, a.workers)
