"""PeriodicEvalScheduler — decides when to dispatch eval jobs.

Supports two schedule grammars:
- ``every_<N>_steps`` — fire when state.step ≥ last_eval_at_step + N
- ``every_<N>_frames`` — fire when state.total_transitions ≥ ...

Driver calls ``due(state)`` each iter; on True, calls ``dispatch(state,
server, jobs)`` to run the EvalServer."""

from __future__ import annotations

import re
from typing import List, Optional

from training.core.eval.job import EvalJob
from training.core.protocols import PipelineState


def _parse_schedule(s: str) -> tuple:
    m = re.match(r'^every_(\d+)_(steps|frames|episodes)$', s)
    if not m:
        raise ValueError(f'PeriodicEvalScheduler: bad schedule {s!r}; expected every_N_{{steps,frames,episodes}}')
    return int(m.group(1)), m.group(2)


class PeriodicEvalScheduler:
    """Cron-style eval trigger. ``schedule`` is the cfg string."""

    def __init__(self, schedule: str, jobs: Optional[List[EvalJob]] = None) -> None:
        self.n, self.unit = _parse_schedule(schedule)
        self.jobs = jobs or []
        self._last_at: int = -1

    def due(self, state: PipelineState) -> bool:
        cur = self._current(state)
        if self._last_at < 0:
            return cur >= self.n
        return cur - self._last_at >= self.n

    def mark_done(self, state: PipelineState) -> None:
        self._last_at = self._current(state)

    def _current(self, state: PipelineState) -> int:
        if self.unit == 'steps':
            return state.step
        if self.unit == 'frames':
            return state.total_transitions
        if self.unit == 'episodes':
            return state.total_episodes
        raise RuntimeError(f'PeriodicEvalScheduler: unhandled unit {self.unit!r}')
