"""Profile the unified-pipeline AZ async self-play main process.

Runs a short async AZ run (``num_actors=4``, ``configs/az/smoke.toml``
+ in-memory overrides) through ``run_pipeline`` under cProfile, then
prints the top functions by cumulative + self time. Goal: see where the
learner (main) process spends wall time with N actor subprocesses + a
shared InferenceServer — input for whether to invest in further
inference-server / trajectory-transport work.

Usage (from repo root):
    .venv/bin/python -m tools.profile.profile_parallel
"""

from __future__ import annotations

import cProfile
import pstats
import tempfile
import time
from pathlib import Path

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms import resolve as resolve_paradigm


def build_cfg():
    """c1-scale async cfg: 4 actors, d_model=64, 400 rollouts, 4 games."""
    return load_cfg(
        'configs/az/smoke.toml',
        overrides=[
            'pipeline.mode=async',
            'pipeline.num_actors=4',
            'paradigm.az.agent.d_model=64',
            'paradigm.az.agent.n_cross_layers=2',
            'paradigm.az.mcts.n_rollouts=400',
            'paradigm.az.total_games=4',
            'paradigm.az.sync_weights_every_train_steps=2',
        ],
    )


def main():
    cfg = build_cfg()
    paradigm = resolve_paradigm(cfg.meta.paradigm)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    with tempfile.TemporaryDirectory(prefix='az_profile_parallel_') as td:
        run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            eval_server=None,
            prebuilt_artifacts_dir=Path(td),
        )
    prof.disable()
    wall = time.perf_counter() - t0

    out_path = Path('artifacts/profile_parallel_main.prof')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prof.dump_stats(str(out_path))

    print(f'\n=== wall: {wall:.1f}s (num_actors={cfg.pipeline.num_actors}, mode={cfg.pipeline.mode}) ===\n')
    st = pstats.Stats(prof).strip_dirs()

    print('--- top 25 by cumulative time (excl. main-loop wait) ---')
    st.sort_stats('cumulative').print_stats(25)

    print('--- top 20 by total (self) time ---')
    st.sort_stats('tottime').print_stats(20)

    print(f'\nprofile saved to {out_path} — inspect with:')
    print(f'  .venv/bin/python -m pstats {out_path}')


if __name__ == '__main__':
    main()
