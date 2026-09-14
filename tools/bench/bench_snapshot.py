"""Micro-benchmark for Game snapshot / clone / restore / step.

Goal: decide whether Python-driven MCTS on the existing ctypes bridge is
feasible. MCTS with 400 rollouts × 30 decision points × 100 games
≈ 1.2M rollouts, each needing ~1 snapshot + 40 steps + 1 restore.

    .venv/bin/python -m tools.bench.bench_snapshot --n-games 50
"""

from __future__ import annotations

import argparse
import time

from gicg_env import GicgEnv


def make_env(team_a, team_b, cards):
    return GicgEnv(
        team_0=team_a,
        team_1=team_b,
        card_pool=cards,
        seed=123,
    )


def bench_step_only(env: GicgEnv, n_games: int) -> tuple[float, int]:
    t0 = time.perf_counter()
    total_steps = 0
    for i in range(n_games):
        env.reset(seed=1000 + i)
        while not env.done:
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                break
            env.step(0)
            total_steps += 1
    return time.perf_counter() - t0, total_steps


def bench_snapshot(env: GicgEnv, n_ops: int) -> float:
    env.reset(seed=42)
    # Run a few steps to leave pristine state
    for _ in range(5):
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0 or env.done:
            break
        env.step(0)
    t0 = time.perf_counter()
    snaps = []
    for _ in range(n_ops):
        snaps.append(env.snapshot())
    elapsed = time.perf_counter() - t0
    for sid in snaps:
        env.snapshot_free(sid)
    return elapsed


def bench_restore(env: GicgEnv, n_ops: int) -> float:
    env.reset(seed=42)
    for _ in range(5):
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0 or env.done:
            break
        env.step(0)
    snap = env.snapshot()
    try:
        t0 = time.perf_counter()
        for _ in range(n_ops):
            env.restore(snap)
        elapsed = time.perf_counter() - t0
    finally:
        env.snapshot_free(snap)
    return elapsed


def bench_clone(env: GicgEnv, n_ops: int) -> float:
    env.reset(seed=42)
    for _ in range(5):
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0 or env.done:
            break
        env.step(0)
    t0 = time.perf_counter()
    twins = []
    for _ in range(n_ops):
        twins.append(env.clone())
    elapsed = time.perf_counter() - t0
    for twin in twins:
        twin.close()
    return elapsed


def bench_mcts_like(env: GicgEnv, n_rollouts: int, rollout_len: int) -> float:
    """Simulate one 'MCTS decision': take snapshot, roll forward with
    random actions rollout_len steps, restore, repeat n_rollouts times.
    """
    env.reset(seed=42)
    for _ in range(5):
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0 or env.done:
            break
        env.step(0)
    t0 = time.perf_counter()
    for _ in range(n_rollouts):
        snap = env.snapshot()
        for _ in range(rollout_len):
            if env.done:
                break
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                break
            env.step(0)
        env.restore(snap)
        env.snapshot_free(snap)
    return time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n-games', type=int, default=20)
    ap.add_argument('--n-ops', type=int, default=10000)
    ap.add_argument('--mcts-rollouts', type=int, default=400)
    ap.add_argument('--mcts-depth', type=int, default=30)
    ap.add_argument(
        '--scenario',
        type=str,
        default='1v1_L1',
        choices=['1v1_L1', '1v1_L12', '2v2_L12', '3v3_L12'],
    )
    args = ap.parse_args()

    if args.scenario == '1v1_L1':
        team_a, team_b = ['赤蝶'], ['墨客']
        cards = ['碌碌无为']
    elif args.scenario == '1v1_L12':
        team_a, team_b = ['赤蝶'], ['墨客']
        cards = ['碌碌无为', '佛跳墙', '美味烧鸡', '占星', '诅咒']
    elif args.scenario == '2v2_L12':
        team_a = ['赤蝶', '墨客']
        team_b = ['猫咪', '刻师傅']
        cards = ['碌碌无为', '佛跳墙', '美味烧鸡', '占星', '诅咒']
    else:  # 3v3_L12
        team_a = ['赤蝶', '墨客', '猫咪']
        team_b = ['刻师傅', '天星', '赤蝶']
        cards = ['碌碌无为', '佛跳墙', '美味烧鸡', '占星', '诅咒']

    print(f'[env] scenario={args.scenario}, team_a={team_a}, team_b={team_b}, n_cards={len(cards)}')

    env = make_env(team_a, team_b, cards)
    try:
        # Warm-up
        env.reset(seed=0)
        for _ in range(3):
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0 or env.done:
                break
            env.step(0)
        env.reset(seed=1)

        dt, steps = bench_step_only(env, args.n_games)
        print(
            f'[step  ] {args.n_games} games, {steps} steps, '
            f'{dt * 1000:.1f} ms ({dt * 1e6 / max(steps, 1):.1f} µs/step, '
            f'{steps / max(dt, 1e-9):.0f} steps/s)'
        )

        dt = bench_snapshot(env, args.n_ops)
        print(
            f'[snap  ] {args.n_ops} ops, {dt * 1000:.1f} ms '
            f'({dt * 1e6 / args.n_ops:.1f} µs/op, {args.n_ops / max(dt, 1e-9):.0f} ops/s)'
        )

        dt = bench_restore(env, args.n_ops)
        print(
            f'[rest  ] {args.n_ops} ops, {dt * 1000:.1f} ms '
            f'({dt * 1e6 / args.n_ops:.1f} µs/op, {args.n_ops / max(dt, 1e-9):.0f} ops/s)'
        )

        dt = bench_clone(env, min(args.n_ops, 2000))
        nn = min(args.n_ops, 2000)
        print(f'[clone ] {nn} ops, {dt * 1000:.1f} ms ({dt * 1e6 / nn:.1f} µs/op, {nn / max(dt, 1e-9):.0f} ops/s)')

        dt = bench_mcts_like(env, args.mcts_rollouts, args.mcts_depth)
        per = dt / args.mcts_rollouts
        print(
            f'[mcts~ ] {args.mcts_rollouts} rollouts × {args.mcts_depth} '
            f'steps, {dt * 1000:.1f} ms ({per * 1e6:.1f} µs/rollout, '
            f'{args.mcts_rollouts / max(dt, 1e-9):.0f} rollouts/s)'
        )

        # Extrapolate: MCTS player per decision (400 rollouts),
        # decisions per game (~30), games per hour
        per_decision = per * 400
        decisions_per_game = 30
        sec_per_game = per_decision * decisions_per_game
        print(
            f'[extrap] @ 400 rollouts/decision, 30 decisions/game: '
            f'{sec_per_game * 1000:.0f} ms/game, '
            f'{3600 / max(sec_per_game, 1e-9):.0f} games/hour'
        )
    finally:
        env.close()


if __name__ == '__main__':
    main()
