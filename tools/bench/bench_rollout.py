"""Micro-bench: Go-side random_rollout vs Python-side _random_rollout_value."""

import random
import time

from gicg_env import GicgEnv
from training.paradigms.az.mcts import _random_rollout_value


def make_env(seed=0):
    env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'], card_pool=None, seed=seed, data_dir='data')
    env.reset(seed=seed)
    return env


def bench_go(n_rollouts=100, max_steps=400):
    env = make_env(seed=1)
    snap = env._engine.snapshot()
    t0 = time.perf_counter()
    total_steps = 0
    for i in range(n_rollouts):
        env._engine.restore(snap)
        _, n = env._engine.random_rollout(seed=i * 1000 + 1, max_steps=max_steps)
        total_steps += n
    elapsed = time.perf_counter() - t0
    env._engine.snapshot_free(snap)
    return elapsed, total_steps


def bench_py(n_rollouts=100, max_steps=400):
    env = make_env(seed=1)
    snap = env._engine.snapshot()
    rng_master = random.Random(1)
    t0 = time.perf_counter()
    total_steps = 0
    for i in range(n_rollouts):
        env._engine.restore(snap)
        rng = random.Random(i * 1000 + 1)
        _, n = _random_rollout_value(env, max_steps, rng)
        total_steps += n
    elapsed = time.perf_counter() - t0
    env._engine.snapshot_free(snap)
    return elapsed, total_steps


if __name__ == '__main__':
    n = 200
    for team_kind in ('team_size=1',):
        print(f'=== {team_kind} ({n} rollouts) ===')
        t_go, s_go = bench_go(n)
        print(
            f'Go:     {t_go * 1000:.1f} ms total, {t_go / n * 1000:.2f} ms/rollout, {s_go} total steps ({s_go / n:.1f} steps/rollout)'
        )
        t_py, s_py = bench_py(n)
        print(
            f'Python: {t_py * 1000:.1f} ms total, {t_py / n * 1000:.2f} ms/rollout, {s_py} total steps ({s_py / n:.1f} steps/rollout)'
        )
        print(f'Speedup: {t_py / t_go:.1f}×')
