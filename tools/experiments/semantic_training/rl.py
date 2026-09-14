"""Resumable terminal-reward policy-gradient fine-tuning from a semantic policy."""

import argparse
from collections import Counter
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import random
import time

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.evaluate import initialize, evaluate
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import update
from tools.runs._train.setup import phase_a_setup
from tools.runs._train.snapshot import phase_b_write_cfg_metadata
from tools.runs.helpers import write_metadata_atomic
from tools.runs import schema
from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.network import AgentConfig
from training.core.config.loader import load_cfg


def run(
    config,
    checkpoint,
    output,
    iterations=8,
    episodes=128,
    workers=16,
    device='cuda',
    resume=None,
    seed=128000,
    dev_seed=129000,
    dev_scenarios=64,
    batch_size=32,
    dev_depth=1,
    opponent_depth=1,
    value_baseline=False,
    temperature=1.0,
    variants=None,
    rule_beta=0.0,
    rule_stride=4,
):
    if not math.isfinite(rule_beta) or rule_beta < 0 or rule_stride < 1:
        raise ValueError('invalid rule auxiliary settings')
    if episodes < 2 or episodes % 2 or iterations < 1:
        raise ValueError('positive iterations and an even episode count >=2 required')
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError('temperature must be finite and positive')
    if variants and episodes % 4:
        raise ValueError('variant mixture requires episodes divisible by four')
    from tools.rule_validation.variants import specification
    from tools.experiments.semantic_training.teams import eval_cases

    eval_cases(load_cfg(config), dev_seed, dev_scenarios)
    variant_identity = specification(variants)[1] if variants else None
    start = time.monotonic()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    state = phase_a_setup(argparse.Namespace(cfg=config, override=['meta.run_label=semantic_rl']))
    phase_b_write_cfg_metadata(state, Path(config))
    run_dir = state.artifacts_dir
    (run_dir / 'ckpts').mkdir()
    torch.set_num_threads(1)
    torch.manual_seed(seed + 1)
    initial = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    shape = AgentConfig(**initial['shape'])
    agent, anchor = SemanticAgent(shape, device), SemanticAgent(shape, device)
    agent.net.load_state_dict(initial['net'])
    anchor.net.load_state_dict(initial['net'])
    anchor.net.requires_grad_(False)
    optimizer = torch.optim.AdamW([p for p in agent.net.parameters() if p.requires_grad], lr=1e-5, weight_decay=0)
    value_optimizer = None
    if value_baseline:
        from tools.experiments.semantic_training.value_baseline import attach

        value_optimizer = torch.optim.AdamW(attach(agent).parameters(), lr=0.0003, weight_decay=0)
    rule_optimizer = None
    if rule_beta:
        from tools.experiments.semantic_training.rule_auxiliary import attach as attach_rule

        rule_optimizer = torch.optim.AdamW(attach_rule(agent).parameters(), lr=0.0003, weight_decay=0)
        if 'rule_head' in initial:
            agent.rule_head.load_state_dict(initial['rule_head'])
    algorithm = 'terminal clipped policy gradient' + (' with state baseline' if value_baseline else '')
    if rule_beta:
        algorithm += ' and engine consequence supervision'
    rng, baseline, first = random.Random(seed + 2), [0.0, 0.0], 1
    anchor_sha = hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()
    settings = dict(
        episodes=episodes,
        master_seed=seed,
        epochs=2,
        lr=1e-5,
        anchor_beta=0.02,
        clip=0.2,
        dev_seed=dev_seed,
        dev_scenarios=dev_scenarios,
        batch_size=batch_size,
        dev_depth=dev_depth,
        opponent_depth=opponent_depth,
        value_baseline=value_baseline,
        temperature=temperature,
    )
    scenario = asdict(load_cfg(config).scenario)
    if rule_beta:
        settings.update(rule_beta=rule_beta, rule_stride=rule_stride, rule_lr=0.0003, rule_schema='1.0.0')
    if variants:
        settings.update(variants=variants, variant_specification_sha256=variant_identity)
    settings['scenario'] = scenario
    if value_baseline:
        settings.update(value_lr=0.0003, value_encoder_grad=False, advantage_gamma=1.0, advantage_lambda=1.0)
    if resume:
        previous = load_checkpoint(resume, map_location='cpu', weights_only=False)
        if previous['algorithm'] != algorithm or previous['anchor_sha256'] != anchor_sha:
            raise ValueError('resume algorithm or anchor mismatch')
        old_settings = {
            'dev_seed': 129000,
            'dev_scenarios': 64,
            'batch_size': 32,
            'dev_depth': 1,
            'opponent_depth': 1,
            'value_baseline': False,
            'temperature': 1.0,
            **previous['settings'],
        }
        if 'scenario' not in old_settings and scenario['char_pool'] is None:
            old_settings['scenario'] = scenario
        if old_settings != settings:
            raise ValueError('resume settings mismatch')
        agent.net.load_state_dict(previous['net'])
        optimizer.load_state_dict(previous['optimizer'])
        if rule_beta:
            agent.rule_head.load_state_dict(previous['rule_head'])
            rule_optimizer.load_state_dict(previous['rule_optimizer'])
        if value_baseline:
            agent.value_head.load_state_dict(previous['value_head'])
            value_optimizer.load_state_dict(previous['value_optimizer'])
        rng.setstate(previous['rng'])
        torch.set_rng_state(previous['torch_rng'])
        if device == 'cuda':
            torch.cuda.set_rng_state_all(previous['cuda_rng'])
        baseline, first = previous['baseline'], previous['iteration'] + 1
    if first > iterations:
        raise ValueError('resume already reached requested iteration count')
    status = dict(
        status='running',
        run=str(run_dir),
        anchor=checkpoint,
        anchor_sha256=anchor_sha,
        algorithm=algorithm,
        settings=settings,
        iterations=[],
    )

    def save_status():
        status['wall_s'] = time.monotonic() - start
        tmp = root / 'result.tmp'
        tmp.write_text(json.dumps(status, indent=2))
        tmp.replace(root / 'result.json')

    def save_model(iteration, path):
        payload = {
            'format': FORMAT,
            'net': agent.net.state_dict(),
            'shape': vars(shape),
            'optimizer': optimizer.state_dict(),
            'rng': rng.getstate(),
            'torch_rng': torch.get_rng_state(),
            'cuda_rng': torch.cuda.get_rng_state_all() if device == 'cuda' else [],
            'baseline': baseline.copy(),
            'iteration': iteration,
            'algorithm': status['algorithm'],
            'anchor_sha256': anchor_sha,
            'settings': settings,
        }
        if value_baseline:
            payload.update(value_head=agent.value_head.state_dict(), value_optimizer=value_optimizer.state_dict())
        if rule_beta:
            payload.update(rule_head=agent.rule_head.state_dict(), rule_optimizer=rule_optimizer.state_dict())
        save_checkpoint(payload, path)

    latest = run_dir / 'ckpts/latest.pt'
    save_model(first - 1, latest)
    save_status()
    try:
        for iteration in range(first, iterations + 1):
            tick = time.monotonic()
            directory = run_dir / f'rollouts/iteration_{iteration}'
            directory.mkdir(parents=True)
            jobs = [
                (iteration, index, str(directory), seed, variants, rule_stride if rule_beta else 0)
                for index in range(episodes)
            ]
            with ProcessPoolExecutor(
                max_workers=workers, initializer=initialize, initargs=(config, str(latest), opponent_depth)
            ) as pool:
                records = list(pool.map(episode, jobs))
            (directory / 'episodes.json').write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            rows = [row for record in records for row in torch.load(record['path'], weights_only=False)]
            before = baseline.copy()
            metrics = update(
                agent,
                anchor,
                optimizer,
                rows,
                baseline,
                rng,
                batch_size=batch_size,
                value_optimizer=value_optimizer,
                temperature=temperature,
                rule_optimizer=rule_optimizer,
                rule_beta=rule_beta,
            )
            for side in (0, 1):
                rewards = [r['reward'] for r in records if r['side'] == side]
                baseline[side] = 0.8 * baseline[side] + 0.2 * sum(rewards) / len(rewards)
            save_model(iteration, latest)
            frozen = run_dir / f'ckpts/iteration_{iteration}.pt'
            save_model(iteration, frozen)
            item = dict(
                iteration=iteration,
                matchup_counts=dict(Counter(r['matchup'] for r in records)),
                rows=len(rows),
                baseline_before=before,
                baseline_after=baseline.copy(),
                collection_score=sum((r['reward'] + 1) / 2 for r in records) / len(records),
                train_wall_s=time.monotonic() - tick,
                **metrics,
            )
            # Fixed development panel; never reuse the earlier acceptance seeds for selection.
            panel = root / f'dev_{iteration}'
            evaluate(
                config,
                str(frozen),
                panel,
                scenarios=dev_scenarios,
                layouts=2,
                workers=workers,
                seed=dev_seed,
                opponent_depth=dev_depth,
            )
            report = json.loads((panel / 'result.json').read_text())
            item.update(dev_score=report['score'], per_layout=report['per_layout'], checkpoint=str(frozen))
            status['iterations'].append(item)
            save_status()
            print(item, flush=True)
        status.update(status='complete', checkpoint=str(latest))
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save_status()
        meta = schema.load_file(run_dir / 'metadata.toml')
        meta.status = 'done' if status['status'] == 'complete' else 'failed'
        meta.exit_code = 0 if meta.status == 'done' else 1
        meta.wall_seconds = time.monotonic() - start
        meta.notes = status['algorithm']
        write_metadata_atomic(run_dir, meta)


if __name__ == '__main__':
    from tools.experiments.semantic_training.rl_cli import main

    main()
