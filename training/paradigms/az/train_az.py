"""AZ training entry point.

Wires together self-play, replay buffer, training, and evaluation
into one call: ``train_az(config)`` returns a ``RunResult``.

Phase 2-ε2 (FU-W4-AZ-rewrite, T2.8) — moved from
``training.paradigms.az.legacy.train_az`` to the adapter top-level.
Phase 2-ζ (T2.ζ) — switched ``legacy.config`` + ``legacy.train_loop.*``
imports off legacy. AZConfig + preset builders are inlined in
``adapter/config.py``; train_loop is inlined as ``adapter/train_loop/``
sub-package. STRICT T2.11 zero-legacy verified by
``test_az_config_train_loop_phase2_zeta.py``.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from training.paradigms.az.config import AZConfig
from training.paradigms.az.train_loop.async_loop import run_async
from training.paradigms.az.train_loop.run_result import RunResult


def train_az(config: AZConfig) -> RunResult:
    """Run the AZ training loop end-to-end."""
    artifacts_dir: Optional[Path] = None
    metrics_fh = None
    if config.write_artifacts:
        ts = datetime.now().strftime('%Y%m%d%H%M')
        artifacts_dir = Path(config.artifacts_root) / f'{ts}_{config.run_label}'
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        metrics_fh = open(artifacts_dir / 'metrics.jsonl', 'w', encoding='utf-8')
        (artifacts_dir / 'run_config.json').write_text(
            json.dumps(
                {
                    'team_0': config.scenario.team_0,
                    'team_1': config.scenario.team_1,
                    'card_pool': config.scenario.card_pool,
                    'deck_padding': config.scenario.deck_padding,
                    'pool': config.scenario.pool,
                    'data_dir': config.scenario.data_dir,
                },
                ensure_ascii=False,
            )
        )
        print(f'[train_az] artifacts dir: {artifacts_dir}')

    log_lock = threading.Lock()
    start_t = time.perf_counter()

    def _log(kind: str, data: dict) -> None:
        with log_lock:
            payload = {'t': round(time.perf_counter() - start_t, 3), **data}
            print(f'[{kind}] {payload}')
            if metrics_fh is not None:
                metrics_fh.write(json.dumps({'kind': kind, **payload}) + '\n')
                metrics_fh.flush()

    try:
        return run_async(config, artifacts_dir, _log)
    finally:
        if metrics_fh is not None:
            metrics_fh.close()


def main():
    from training.paradigms.az.config import fixed_1v1_config

    cfg = fixed_1v1_config()
    train_az(cfg)


if __name__ == '__main__':
    main()
