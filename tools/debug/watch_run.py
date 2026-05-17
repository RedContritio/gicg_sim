"""Live dashboard for a running or finished AZ run.

Tails ``metrics.jsonl`` (a per-event JSONL file produced by
``training.train_az``) and prints a compact status line every
few seconds. Works on live runs (follows the file as it grows)
or on completed runs (parses everything and exits on the final
``done`` event).

Usage from repo root::

    .venv/bin/python -m tools.watch_run artifacts/<ts>_<label>/metrics.jsonl
    .venv/bin/python -m tools.watch_run artifacts/<ts>_<label>/metrics.jsonl --interval 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional


class RunState:
    """Aggregates incremental updates from an AZ metrics.jsonl stream."""

    def __init__(self) -> None:
        self.elapsed: float = 0.0
        self.games: int = 0
        self.train_ticks: int = 0
        self.train_steps_total: int = 0
        self.loss_window: deque = deque(maxlen=50)  # list[dict]
        self.last_arena_wr: Optional[float] = None
        self.replaces: int = 0
        self.last_server_stats: dict = {}
        self.stale_gap_window: deque = deque(maxlen=50)  # list[int]
        self.wall_window: deque = deque(maxlen=50)  # list[float]
        self.last_cpu: float = -1.0
        self.last_rss_mb: float = -1.0
        self.diverged: bool = False
        self.done: bool = False

    def update(self, ev: dict) -> None:
        kind = ev.get('kind', '?')
        t = float(ev.get('t', 0.0))
        if t > self.elapsed:
            self.elapsed = t

        if kind == 'selfplay':
            self.games += 1
            if 'stale_gap' in ev and ev['stale_gap'] >= 0:
                self.stale_gap_window.append(int(ev['stale_gap']))
            if 'wall_s' in ev and ev['wall_s'] >= 0:
                self.wall_window.append(float(ev['wall_s']))
        elif kind == 'train':
            self.train_steps_total += 1
            self.loss_window.append(
                {
                    'v': float(ev.get('value', 0.0)),
                    'p': float(ev.get('policy', 0.0)),
                    'tot': float(ev.get('total', 0.0)),
                }
            )
        elif kind == 'arena':
            self.last_arena_wr = float(ev.get('win_rate', 0.0))
        elif kind == 'replace':
            self.replaces += 1
        elif kind == 'server_stats':
            self.last_server_stats = ev
        elif kind == 'system':
            self.last_cpu = float(ev.get('cpu_pct', -1.0))
            self.last_rss_mb = float(ev.get('rss_mb', -1.0))
        elif kind == 'diverged':
            self.diverged = True
        elif kind == 'done':
            self.done = True

    # --- derived fields ---------------------------------------------------- #

    def games_per_hour(self) -> float:
        if self.elapsed <= 0:
            return 0.0
        return self.games * 3600.0 / self.elapsed

    def loss_avg(self) -> dict:
        if not self.loss_window:
            return {'v': 0.0, 'p': 0.0, 'tot': 0.0}
        n = len(self.loss_window)
        return {
            'v': sum(x['v'] for x in self.loss_window) / n,
            'p': sum(x['p'] for x in self.loss_window) / n,
            'tot': sum(x['tot'] for x in self.loss_window) / n,
        }

    def stale_gap_avg(self) -> float:
        if not self.stale_gap_window:
            return -1.0
        return sum(self.stale_gap_window) / len(self.stale_gap_window)

    def wall_avg(self) -> float:
        if not self.wall_window:
            return -1.0
        return sum(self.wall_window) / len(self.wall_window)

    def format_line(self) -> str:
        loss = self.loss_avg()
        s = self.last_server_stats
        parts = [
            f'[{self.elapsed / 60:6.1f}m]',
            f'games={self.games:4d}({self.games_per_hour():5.0f}/hr)',
            f'wall/g={self.wall_avg():.1f}s' if self.wall_window else 'wall/g=-',
            f'train={self.train_steps_total:4d}',
            f'loss v/p/tot={loss["v"]:.2f}/{loss["p"]:.2f}/{loss["tot"]:.2f}',
        ]
        if self.last_arena_wr is not None:
            parts.append(f'arena={self.last_arena_wr:.2f}')
        if self.replaces:
            parts.append(f'rpl={self.replaces}')
        if s:
            parts.append(f'batch={s.get("batch_mean", 0):.1f}/p95={s.get("batch_p95", 0)}')
            parts.append(f'reqs/s={s.get("reqs_per_s", 0):.0f}')
        if self.stale_gap_window:
            parts.append(f'stale={self.stale_gap_avg():.1f}')
        if self.last_cpu >= 0:
            parts.append(f'cpu={self.last_cpu:.0f}%')
        if self.last_rss_mb >= 0:
            parts.append(f'rss={self.last_rss_mb:.0f}MB')
        if self.diverged:
            parts.append('DIVERGED')
        return ' '.join(parts)


def _read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Read new lines from ``path`` starting at ``offset``. Returns
    (lines, new_offset)."""
    if not path.exists():
        return [], offset
    with open(path, 'r', encoding='utf-8') as f:
        f.seek(offset)
        chunk = f.read()
        new_offset = f.tell()
    lines = [l.strip() for l in chunk.splitlines() if l.strip()]
    return lines, new_offset


def follow(path: Path, interval: float) -> None:
    """Poll the metrics file (and the sibling
    ``gauntlet_results.jsonl`` produced by the standalone
    eval_service) forever, printing one status line every
    ``interval`` seconds."""
    state = RunState()
    offset = 0
    gauntlet_path = path.parent / 'gauntlet_results.jsonl'
    gauntlet_offset = 0
    last_print = 0.0
    while True:
        # Read metrics.jsonl
        lines, offset = _read_new_lines(path, offset)
        for line in lines:
            try:
                state.update(json.loads(line))
            except json.JSONDecodeError:
                continue

        # Read gauntlet_results.jsonl (from eval_service)
        glines, gauntlet_offset = _read_new_lines(gauntlet_path, gauntlet_offset)
        for line in glines:
            try:
                ev = json.loads(line)
                ev['kind'] = 'gauntlet'
                state.update(ev)
            except json.JSONDecodeError:
                continue

        now = time.monotonic()
        if now - last_print >= interval:
            print(state.format_line(), flush=True)
            last_print = now

        if state.done or state.diverged:
            print(state.format_line(), flush=True)
            return

        time.sleep(min(0.5, interval / 2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metrics_path', type=Path, help='path to metrics.jsonl')
    parser.add_argument(
        '--interval',
        type=float,
        default=5.0,
        help='seconds between status prints (default 5)',
    )
    args = parser.parse_args()

    if not args.metrics_path.exists():
        # Wait up to 10s for the file to appear — handy when you
        # start watch_run before train_az has opened the file.
        t0 = time.monotonic()
        while not args.metrics_path.exists():
            if time.monotonic() - t0 > 10.0:
                print(f'metrics file not found: {args.metrics_path}', file=sys.stderr)
                sys.exit(1)
            time.sleep(0.2)

    try:
        follow(args.metrics_path, interval=args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
