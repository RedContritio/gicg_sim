"""MetricsLogger — metrics.jsonl + optional TensorBoard.

Used by the pipeline driver. Each ``log_*`` method emits one jsonl row
+ optionally TB scalars. Caller passes the artifacts_dir at init."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class MetricsLogger:
    """Append-only metrics writer. ``close()`` flushes + closes handles."""

    def __init__(self, artifacts_dir: Optional[Path], enable_tb: bool = True) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.enable_tb = enable_tb
        self._metrics_fh = None
        self._tb_writer = None
        self._t_start = time.perf_counter()

        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self._metrics_fh = open(self.artifacts_dir / 'metrics.jsonl', 'a', encoding='utf-8')
            if enable_tb:
                try:
                    from torch.utils.tensorboard import SummaryWriter

                    self._tb_writer = SummaryWriter(log_dir=str(self.artifacts_dir / 'tb'))
                except ImportError:
                    self._tb_writer = None

    def log(self, kind: str, payload: dict) -> None:
        """Append one row to metrics.jsonl with ``kind`` + payload +
        wall_seconds for cross-row alignment."""
        if self._metrics_fh is None:
            return
        row = {'kind': kind, 'wall_s': round(time.perf_counter() - self._t_start, 3), **payload}
        self._metrics_fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        self._metrics_fh.flush()

    def log_iter(self, state, breakdown: dict) -> None:
        self.log(
            'iter',
            {
                'step': state.step,
                'frames': state.total_transitions,
                'episodes': state.total_episodes,
                'train_steps': state.train_steps,
                **breakdown,
            },
        )

    def log_eval(self, state, report) -> None:
        """Log an EvalReport-like object. Accepts dict for plain values."""
        if hasattr(report, '__dataclass_fields__'):
            from dataclasses import asdict

            r = asdict(report)
        else:
            r = dict(report)
        self.log('eval', {'step': state.step, **r})

    def add_scalar(self, tag: str, value: float, step: int) -> None:
        if self._tb_writer is not None:
            self._tb_writer.add_scalar(tag, value, step)

    def close(self) -> None:
        if self._metrics_fh is not None:
            self._metrics_fh.close()
            self._metrics_fh = None
        if self._tb_writer is not None:
            self._tb_writer.close()
            self._tb_writer = None
