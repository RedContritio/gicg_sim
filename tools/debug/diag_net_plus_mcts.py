"""Diagnostic: network-guided MCTS vs baseline opponents.

Unlike the stock gauntlet (which uses greedy argmax on the policy
head alone), this diagnostic wires the trained network into
``mcts_search`` at inference time — closer to how AlphaZero actually
plays. Tests whether adding search recovers the strength that the
raw policy head lacks at d_model=64.

Each champion plays N games per opponent as:

    network + MCTS K rollouts   vs   pure MCTS J rollouts

If ``network + MCTS K`` > pure ``MCTS K`` win-rate, the network's
prior is adding value beyond a uniform prior. If it also beats
pure ``MCTS J`` for J > K, the network + search is net-stronger.

Usage::

    .venv/bin/python -m tools.diag_net_plus_mcts artifacts/<run>/
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np

from gicg_env import GicgEnv
from gicg_env.env import _terminal_z
from training.paradigms.az.config import fixed_1v1_config
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig, mcts_search
from training.paradigms.az.network import Agent
from training.paradigms.az.pool_spec import resolve_pool_refs
from training.core.matchup.players import MCTSPlayer


def run_series(
    *,
    name: str,
    net_agent: Agent,
    opp_player,
    env_factory,
    spec: SharedFixedPool,
    n_games: int,
    net_mcts_rollouts: int,
) -> dict:
    """Play ``n_games`` between the network-guided MCTS and ``opp_player``,
    alternating sides. Returns wins/losses/draws."""
    mcts_cfg = MCTSConfig(
        n_rollouts=net_mcts_rollouts,
        max_rollout_depth=400,
        dirichlet_eps=0.0,  # no noise at eval time
        temperature=0.0,  # argmax on visit counts
        temperature_switch_step=0,
    )
    rng = random.Random(7777)
    wins = losses = draws = 0
    t0 = time.perf_counter()
    for g in range(n_games):
        net_side = g % 2
        env = env_factory(g)
        net_agent.game_start(env.static_obs)
        try:
            # Advance past PhaseSelectActive
            while env._engine.phase == 1:
                env.step(0)
                if env.done:
                    break
            while not env.done:
                acting = env.acting_player
                if acting == net_side:
                    chosen, _info = mcts_search(
                        env,
                        net_agent,
                        spec,
                        rng,
                        viewing_player=acting,
                        config=mcts_cfg,
                        game_step=0,
                    )
                else:
                    chosen = opp_player.select_action(env)
                _, _, done, step_info = env.step(chosen)
                if step_info.get('need_target'):
                    raise RuntimeError('legacy PendingCardTarget path')
            winner = env._engine.winner
            if winner == net_side:
                wins += 1
            elif winner == (1 - net_side):
                losses += 1
            else:
                draws += 1
        finally:
            net_agent.game_end()
            env.close()
    dt = time.perf_counter() - t0
    decisive = max(1, wins + losses)
    wr = wins / decisive
    return {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'wr': round(wr, 3),
        'wall_s': round(dt, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--n', type=int, default=8, help='games per config (default 8)')
    parser.add_argument(
        '--net_rollouts',
        type=int,
        default=100,
        help='MCTS rollouts used by the network player (default 100)',
    )
    args = parser.parse_args()

    ckpts = sorted((args.run_dir / 'ckpts').glob('champion_g*.pt'))
    if not ckpts:
        print(f'no champions found under {args.run_dir}/ckpts/', file=sys.stderr)
        return 1

    cfg = fixed_1v1_config(data_dir='data')
    pool_refs = resolve_pool_refs(cfg.scenario)
    spec = SharedFixedPool(pool_refs)

    def env_factory(i: int) -> GicgEnv:
        seed = 88000 + i
        env = GicgEnv(
            cfg.scenario.team_0,
            cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=seed,
            data_dir=cfg.scenario.data_dir,
        )
        env.reset(seed=seed)
        return env

    opponents = [
        ('mcts_50', MCTSPlayer(n_rollouts=50, max_rollout_depth=400, seed=1)),
        ('mcts_200', MCTSPlayer(n_rollouts=200, max_rollout_depth=400, seed=2)),
    ]

    print(
        f'Diag: network+MCTS{args.net_rollouts} vs {[o[0] for o in opponents]} '
        f'× {args.n} games per pair, on {len(ckpts)} champions',
        flush=True,
    )
    for ckpt in ckpts:
        agent = Agent(cfg.agent)
        agent.load(str(ckpt))
        agent.net.eval()
        print(f'--- {ckpt.name} ---', flush=True)
        for name, opp in opponents:
            r = run_series(
                name=name,
                net_agent=agent,
                opp_player=opp,
                env_factory=env_factory,
                spec=spec,
                n_games=args.n,
                net_mcts_rollouts=args.net_rollouts,
            )
            print(f'  vs {name}: {r}', flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
