"""Short smoke to capture MCTSProfile data under C1v4-like training.

Purpose: empirically measure rollout / eval / ctypes time share in the
training scenario (IS-MCTS + virtual-loss + lambda-mix), which the
tools/mcts_player.py probe cannot reproduce.

Writes metrics.jsonl with per-game mcts_profile fields.

Run from repo root::

    nohup .venv/bin/python -m tools.profile_smoke \\
        > /tmp/profile_smoke.log 2>&1 &
"""

from __future__ import annotations

import sys
import time

from training.paradigms.az.config import fixed_1v1_config
from training.paradigms.az.train_az import train_az


def main() -> int:
    t0 = time.perf_counter()
    cfg = fixed_1v1_config(data_dir='data')
    # minimize core contention with the running C1v4 training
    cfg.n_workers = 1
    cfg.mcts.parallel_rollouts = 1
    # small sample; ~30 searches/game × 50 = ~1500 profile records
    cfg.n_games = 50
    # disable evaluation paths — we only want selfplay profile data
    cfg.games_per_arena = 0
    cfg.games_per_gauntlet = 0
    cfg.checkpoint_every_n_games = 0
    # C1v4 runs at g971 with lambda≈0.51 — match that for realistic
    # eval/rollout mix; skip annealing so the whole smoke uses one
    # lambda setting.
    cfg.mcts.lambda_anneal_games = 0
    cfg.mcts.value_mix_lambda = 0.5
    cfg.mcts.prior_mix_lambda = 0.5
    cfg.run_label = 'profile_smoke'

    print(
        f'=== profile_smoke === n_workers={cfg.n_workers} '
        f'par={cfg.mcts.parallel_rollouts} n_games={cfg.n_games} '
        f'rollouts={cfg.mcts.n_rollouts} '
        f'lambda={cfg.mcts.value_mix_lambda}',
        flush=True,
    )

    result = train_az(cfg)
    elapsed = time.perf_counter() - t0
    print(
        f'=== DONE === elapsed={elapsed:.1f}s games={result.n_games_played} artifacts_dir={result.artifacts_dir}',
        flush=True,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
