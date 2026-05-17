"""Profile the main process of the parallel self-play path.

Runs a short c1-scale train_az loop with n_workers=4 under cProfile,
then prints the top functions by cumulative + self time. Goal: see
where the main process actually spends wall time so we can decide
whether to invest in inference-server refactor (B) or shared-memory
trajectory transport (D) or both.

Usage (from repo root):
    .venv/bin/python -m tools.profile_parallel
"""

from __future__ import annotations

import cProfile
import pstats
import time
from pathlib import Path

from training.paradigms.az.config import smoke_config
from training.paradigms.az.train_az import train_az


def build_cfg():
    cfg = smoke_config(data_dir='data')
    cfg.agent.d_model = 64
    cfg.agent.n_cross_layers = 2
    cfg.mcts.n_rollouts = 400
    cfg.n_games = 4
    cfg.n_workers = 4
    cfg.sync_interval_games = 2
    cfg.write_artifacts = False
    return cfg


def main():
    cfg = build_cfg()
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    train_az(cfg)
    prof.disable()
    wall = time.perf_counter() - t0

    out_path = Path('artifacts/profile_parallel_main.prof')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prof.dump_stats(str(out_path))

    print(f'\n=== wall: {wall:.1f}s ({wall / cfg.n_games:.2f}s/game, n_workers={cfg.n_workers}) ===\n')
    st = pstats.Stats(prof).strip_dirs()

    print('--- top 20 by cumulative time (excl. main-loop wait) ---')
    st.sort_stats('cumulative').print_stats(25)

    print('--- top 20 by total (self) time ---')
    st.sort_stats('tottime').print_stats(20)

    print(f'\nprofile saved to {out_path} — inspect with:')
    print(f'  .venv/bin/python -m pstats {out_path}')


if __name__ == '__main__':
    main()
