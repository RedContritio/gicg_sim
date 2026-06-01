"""Short serial AZ self-play profile via the unified pipeline.

Drives a serial AZ run (``configs/az/smoke.toml`` — already
``mode=serial`` / ``num_actors=1``) through ``run_pipeline`` so the
operator can capture MCTSProfile timing data (rollout / eval / ctypes
share) under realistic IS-MCTS self-play. Self-play correctness +
profile fields come from the same collector production uses; this just
drives a short run + reports wall. eval_server=None disables the
periodic gauntlet path (the legacy champion arena is gone post 方向 C).

Run from repo root::

    .venv/bin/python -m tools.profile.profile_smoke
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms import resolve as resolve_paradigm


def main() -> int:
    t0 = time.perf_counter()
    # smoke.toml ships serial / num_actors=1; bump games + rollouts for a
    # meatier profile sample, enable mcts profile capture, and pin a fixed
    # lambda mix (skip annealing) so the whole smoke uses one setting.
    cfg = load_cfg(
        'configs/az/smoke.toml',
        overrides=[
            'paradigm.az.total_games=50',
            'paradigm.az.mcts.n_rollouts=200',
            'paradigm.az.mcts.profile=true',
            'paradigm.az.mcts.lambda_anneal_games=0',
            'paradigm.az.mcts.value_mix_lambda=0.5',
            'paradigm.az.mcts.prior_mix_lambda=0.5',
        ],
    )
    paradigm = resolve_paradigm(cfg.meta.paradigm)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    print(
        f'=== profile_smoke === mode={cfg.pipeline.mode} '
        f'num_actors={cfg.pipeline.num_actors} (total_games=50, rollouts=200)',
        flush=True,
    )

    with tempfile.TemporaryDirectory(prefix='az_profile_smoke_') as td:
        state = run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            eval_server=None,
            prebuilt_artifacts_dir=Path(td),
        )

    elapsed = time.perf_counter() - t0
    print(f'=== DONE === elapsed={elapsed:.1f}s step={state.step}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
