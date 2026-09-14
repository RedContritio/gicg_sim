"""Command-line options for semantic RL and optional rule auxiliary training."""

import argparse
from tools.experiments.semantic_training.rl import run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--iterations', type=int, default=8)
    p.add_argument('--episodes', type=int, default=128)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--device', default='cuda', choices=['cuda', 'cpu'])
    p.add_argument('--resume')
    p.add_argument('--seed', type=int, default=128000)
    p.add_argument('--dev-seed', type=int, default=129000)
    p.add_argument('--dev-scenarios', type=int, default=64)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--dev-depth', type=int, choices=[1, 2], default=1)
    p.add_argument('--opponent-depth', type=int, choices=[1, 2], default=1)
    p.add_argument('--value-baseline', action='store_true')
    p.add_argument('--temperature', type=float, default=1.0)
    p.add_argument('--variants')
    p.add_argument('--rule-beta', type=float, default=0.0)
    p.add_argument('--rule-stride', type=int, default=4)
    p.add_argument('--learning-rate', type=float, default=1e-5)
    a = p.parse_args()
    run(
        a.config,
        a.checkpoint,
        a.output,
        a.iterations,
        a.episodes,
        a.workers,
        a.device,
        a.resume,
        a.seed,
        a.dev_seed,
        a.dev_scenarios,
        a.batch_size,
        a.dev_depth,
        a.opponent_depth,
        a.value_baseline,
        a.temperature,
        a.variants,
        a.rule_beta,
        a.rule_stride,
        a.learning_rate,
    )
