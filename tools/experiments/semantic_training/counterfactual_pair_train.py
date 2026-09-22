"""Train a semantic policy from common-seed paired action preferences."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

import torch

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.paired_rl_rollout import DECISION_TYPES, episode
from tools.experiments.semantic_training.paired_rl_update import update_paired
from tools.experiments.semantic_training.player_loader import load_semantic_agent, load_semantic_payload
from training.core.artifact_io import save_checkpoint
from training.core.network import AgentConfig


def _save_model(agent, initial, shape, settings, iteration, path):
    payload = {
        'format': initial['format'],
        'net': agent.net.state_dict(),
        'shape': vars(shape),
        'iteration': iteration,
        'algorithm': 'common-seed terminal action preference',
        'settings': settings,
    }
    if 'use_consequences' in initial:
        payload['use_consequences'] = initial['use_consequences']
    if hasattr(agent, 'value_head') and 'value_head' in initial:
        payload['value_head'] = agent.value_head.state_dict()
        payload['value_encoding'] = 'signed_outcome'
    if hasattr(agent, 'rule_adapter') and 'rule_adapter' in initial:
        payload['rule_adapter'] = agent.rule_adapter.state_dict()
    save_checkpoint(payload, path)


def run(
    config,
    checkpoint,
    output,
    *,
    iterations=1,
    episodes=8,
    workers=1,
    device='cpu',
    seed=932000,
    opponent_depth=2,
    pair_repeats=2,
    learning_rate=1e-5,
    anchor_beta=0.02,
    batch_size=32,
    temperature=1.0,
    max_steps=512,
    variants=None,
    allow_unverified_checkpoint=False,
    evaluate_dev=False,
    dev_seed=935000,
    dev_scenarios=8,
    decision_type='ordinary',
):
    if min(iterations, episodes, workers, pair_repeats) < 1:
        raise ValueError('positive training budgets required')
    if decision_type not in DECISION_TYPES:
        raise ValueError(f'unknown decision type: {decision_type}')
    initial = load_semantic_payload(checkpoint, verify_provenance=not allow_unverified_checkpoint)
    shape = AgentConfig(**initial['shape'])
    agent = load_semantic_agent(checkpoint, device=device, verify_provenance=not allow_unverified_checkpoint)
    anchor = load_semantic_agent(checkpoint, device=device, verify_provenance=not allow_unverified_checkpoint)
    anchor.net.requires_grad_(False)
    optimizer = torch.optim.AdamW(agent.net.parameters(), lr=learning_rate, weight_decay=0)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'ckpts').mkdir()
    settings = {
        'episodes': episodes,
        'master_seed': seed,
        'pair_repeats': pair_repeats,
        'lr': learning_rate,
        'anchor_beta': anchor_beta,
        'batch_size': batch_size,
        'temperature': temperature,
        'opponent_depth': opponent_depth,
        'max_steps': max_steps,
        'variants': variants,
        'decision_type': decision_type,
    }
    player_spec = {
        'type': 'semantic_rl',
        'ckpt': str(checkpoint),
        'allow_unverified_checkpoint': allow_unverified_checkpoint,
    }
    status = {'status': 'running', 'algorithm': 'common-seed terminal action preference', 'iterations': []}
    start = time.monotonic()

    def save_status():
        status['wall_s'] = time.monotonic() - start
        tmp = root / 'result.tmp'
        tmp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        tmp.replace(root / 'result.json')

    latest = root / 'ckpts/latest.pt'
    _save_model(agent, initial, shape, settings, 0, latest)
    save_status()
    try:
        for iteration in range(1, iterations + 1):
            tick = time.monotonic()
            directory = root / 'rollouts' / f'iteration_{iteration}'
            directory.mkdir(parents=True)
            collection_checkpoint = checkpoint if iteration == 1 else latest
            collection_spec = dict(player_spec, ckpt=str(collection_checkpoint))
            jobs = [
                (
                    iteration,
                    index,
                    str(directory),
                    seed,
                    variants,
                    pair_repeats,
                    max_steps,
                    opponent_depth,
                    decision_type,
                )
                for index in range(episodes)
            ]
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=ev.initialize,
                initargs=(config, str(collection_checkpoint), opponent_depth, collection_spec),
            ) as pool:
                records = list(pool.map(episode, jobs))
            (directory / 'episodes.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            rows = [row for record in records for row in torch.load(record['path'], weights_only=False)]
            metrics = update_paired(
                agent,
                anchor,
                optimizer,
                rows,
                batch_size=batch_size,
                temperature=temperature,
                anchor_beta=anchor_beta,
            )
            frozen = root / 'ckpts' / f'iteration_{iteration}.pt'
            _save_model(agent, initial, shape, settings, iteration, frozen)
            _save_model(agent, initial, shape, settings, iteration, latest)
            item = {
                'iteration': iteration,
                'episodes': len(records),
                'decision_type': decision_type,
                'rows': len(rows),
                'root_seen': sum(record['root_seen'] for record in records),
                'root_selected': sum(record['root_selected'] for record in records),
                'pairs': sum(record['pairs'] for record in records),
                'ties': sum(record['ties'] for record in records),
                'continuation_steps': sum(record['continuation_steps'] for record in records),
                'train_wall_s': time.monotonic() - tick,
                'checkpoint': str(frozen),
                **metrics,
            }
            if evaluate_dev:
                panel = root / f'dev_{iteration}'
                ev.evaluate(
                    config,
                    str(frozen),
                    panel,
                    scenarios=dev_scenarios,
                    layouts=2,
                    workers=workers,
                    seed=dev_seed,
                    opponent_depth=opponent_depth,
                )
                report = json.loads((panel / 'result.json').read_text(encoding='utf-8'))
                item['dev_score'] = report['score']
            status['iterations'].append(item)
            save_status()
            print(item, flush=True)
        status.update(status='complete', checkpoint=str(latest))
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--iterations', type=int, default=1)
    parser.add_argument('--episodes', type=int, default=8)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--seed', type=int, default=932000)
    parser.add_argument('--opponent-depth', type=int, choices=(1, 2), default=2)
    parser.add_argument('--pair-repeats', type=int, default=2)
    parser.add_argument('--learning-rate', type=float, default=1e-5)
    parser.add_argument('--anchor-beta', type=float, default=0.02)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--temperature', type=float, default=1.0)
    parser.add_argument('--max-steps', type=int, default=512)
    parser.add_argument('--variants', default=None)
    parser.add_argument('--allow-unverified-checkpoint', action='store_true')
    parser.add_argument('--dev-eval', action='store_true')
    parser.add_argument('--dev-seed', type=int, default=935000)
    parser.add_argument('--dev-scenarios', type=int, default=8)
    parser.add_argument('--decision-type', choices=('ordinary', 'reroll', 'all'), default='ordinary')
    args = parser.parse_args()
    run(
        args.config,
        args.checkpoint,
        args.output,
        iterations=args.iterations,
        episodes=args.episodes,
        workers=args.workers,
        device=args.device,
        seed=args.seed,
        opponent_depth=args.opponent_depth,
        pair_repeats=args.pair_repeats,
        learning_rate=args.learning_rate,
        anchor_beta=args.anchor_beta,
        batch_size=args.batch_size,
        temperature=args.temperature,
        max_steps=args.max_steps,
        variants=args.variants,
        allow_unverified_checkpoint=args.allow_unverified_checkpoint,
        evaluate_dev=args.dev_eval,
        dev_seed=args.dev_seed,
        dev_scenarios=args.dev_scenarios,
        decision_type=args.decision_type,
    )


if __name__ == '__main__':
    main()
