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
    p.add_argument('--anchor-beta', type=float, default=0.02)
    p.add_argument('--reroll-fraction', type=float, default=1 / 3)
    p.add_argument('--allow-unverified-checkpoint', action='store_true')
    p.add_argument('--no-dev-eval', action='store_true')
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
        seed=a.seed,
        dev_seed=a.dev_seed,
        dev_scenarios=a.dev_scenarios,
        batch_size=a.batch_size,
        dev_depth=a.dev_depth,
        opponent_depth=a.opponent_depth,
        value_baseline=a.value_baseline,
        temperature=a.temperature,
        variants=a.variants,
        rule_beta=a.rule_beta,
        rule_stride=a.rule_stride,
        learning_rate=a.learning_rate,
        anchor_beta=a.anchor_beta,
        reroll_fraction=a.reroll_fraction,
        allow_unverified_checkpoint=a.allow_unverified_checkpoint,
        evaluate_dev=not a.no_dev_eval,
    )


if __name__ == '__main__':
    main()
