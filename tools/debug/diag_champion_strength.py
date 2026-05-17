"""Quick absolute-strength diag on saved C1 champion checkpoints.

Loads each ``champion_gNNNNN.pt`` under the given run dir and runs
a short matchup panel (random + mcts_pure_N) so the operator can see
the real win-rate trajectory of the champions that HAVE been saved
(replaces only — failed arenas don't produce a ckpt).

In-process: uses ``training.core.matchup.matchup.run_matchup`` directly rather
than going through eval_service (no socket round-trip needed for a
one-shot diag).

Usage::

    .venv/bin/python -m tools.diag_champion_strength artifacts/<run>/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from training.paradigms.az.config import fixed_1v1_config
from training.core.matchup.matchup import run_matchup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument(
        '--n',
        type=int,
        default=10,
        help='games per side-assignment (default 10; total games per opponent = 2x)',
    )
    parser.add_argument(
        '--rollouts',
        type=int,
        nargs='+',
        default=[50],
        help='mcts_pure rollout counts to test against (default: [50])',
    )
    args = parser.parse_args()

    ckpts = sorted(args.run_dir.glob('champion_g*.pt'))
    if not ckpts:
        print(f'no champion_g*.pt found under {args.run_dir}', file=sys.stderr)
        return 1

    cfg = fixed_1v1_config(data_dir='data')

    print(
        f'Diag: {len(ckpts)} champions, {args.n * 2} games each vs random + mcts_pure at {args.rollouts}',
        flush=True,
    )
    for ckpt in ckpts:
        challenger = {'type': 'az', 'ckpt': str(ckpt), 'n_simulations': 0}
        opponents: list[tuple[str, dict]] = [('random', {'type': 'random'})]
        for r in args.rollouts:
            opponents.append(
                (
                    f'mcts_{r}',
                    {'type': 'mcts_pure', 'n_simulations': int(r)},
                )
            )

        wrs: dict = {}
        t0 = time.perf_counter()
        for name, opp in opponents:
            result = run_matchup(
                players=[challenger, opp],
                mode='fixed',
                team_0=cfg.scenario.team_0,
                team_1=cfg.scenario.team_1,
                card_pool=cfg.scenario.card_pool,
                games_per_cell=args.n,
                max_game_steps=cfg.max_game_steps,
                seed=77777,
                data_dir=cfg.scenario.data_dir,
            )
            wrs[name] = round(result.aggregate.win_rate, 3)
        dt = time.perf_counter() - t0
        print(f'  {ckpt.name}: {wrs}  ({dt:.1f}s)', flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
