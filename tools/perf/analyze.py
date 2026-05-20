"""tools.perf.analyze — offline aggregator for perf trace JSONL.

Reads ``artifacts/_perf_logs/*.jsonl`` (or a custom dir passed positionally),
aggregates per-(role, stage), prints a breakdown table + cross-role
correlation, marks the largest %-of-role stage with 🔥.

The JSONL is itself already aggregated (one row per ~200 events with
mean/p50/p95/max/sum/n). The analyzer re-aggregates by summing ``sum_ms``
+ ``n`` across rows and pooling ``max_ms`` (true max). Mean is recomputed
from the summed sum / summed n. Percentiles (p50/p95) become inexact when
rolled up across windows (we'd need raw samples for a true p95); the
analyzer reports a *weighted mean of window p95s* as a usable proxy + the
true max — both labelled to make the limitation explicit.

Usage::

    .venv/bin/python -m tools.perf.analyze                       # default dir
    .venv/bin/python -m tools.perf.analyze /tmp/perf_n4/

Stdlib-only; no numpy / pandas.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _load_jsonl_dir(d: Path) -> dict:
    """Returns dict[(role, id_int)] -> list[row]. Skips empty/garbage files."""
    out: dict = defaultdict(list)
    for path in sorted(d.glob('*.jsonl')):
        # role + id encoded in filename for cross-check
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = row.get('role', 'unknown')
            id_ = int(row.get('id', 0))
            out[(role, id_)].append(row)
    return out


def _aggregate(rows: list) -> dict:
    """Roll up windows. Returns dict[stage] -> aggregate."""
    by_stage: dict = defaultdict(
        lambda: {'n': 0, 'sum_ms': 0.0, 'max_ms': 0.0, 'p95_weighted_sum': 0.0, 'p95_weight': 0}
    )
    for row in rows:
        for stage, st in row.get('stages', {}).items():
            agg = by_stage[stage]
            n = st.get('n', 0)
            agg['n'] += n
            agg['sum_ms'] += st.get('sum_ms', 0.0)
            agg['max_ms'] = max(agg['max_ms'], st.get('max_ms', 0.0))
            # Weighted by sample count so a tiny tail window doesn't
            # dominate the rollup
            agg['p95_weighted_sum'] += st.get('p95_ms', 0.0) * n
            agg['p95_weight'] += n
    for stage, agg in by_stage.items():
        agg['mean_ms'] = agg['sum_ms'] / max(agg['n'], 1)
        agg['p95_ms_approx'] = agg['p95_weighted_sum'] / max(agg['p95_weight'], 1)
    return dict(by_stage)


def _fmt_ms(v: float) -> str:
    if v >= 1000:
        return f'{v / 1000:.2f}s'
    if v >= 1:
        return f'{v:.2f}ms'
    if v >= 0.001:
        return f'{v * 1000:.1f}us'
    return f'{v * 1e6:.0f}ns'


def _print_role_table(role: str, id_: int, agg: dict) -> None:
    total_ms = sum(s['sum_ms'] for s in agg.values())
    # Stages whose name looks like a "value" emitter (e.g. *.size) are
    # treated as observed values not durations — skip pct-of-role.
    items = sorted(agg.items(), key=lambda kv: kv[1]['sum_ms'], reverse=True)
    print(f'\n=== role={role} id={id_}  total_traced={_fmt_ms(total_ms)} ===')
    print(f'  {"stage":<40} {"n":>8} {"sum":>10} {"pct":>6} {"mean":>10} {"p95~":>10} {"max":>10}')
    print(f'  {"-" * 40} {"-" * 8} {"-" * 10} {"-" * 6} {"-" * 10} {"-" * 10} {"-" * 10}')
    max_pct = 0.0
    max_stage = ''
    for stage, st in items:
        is_value = stage.endswith('.size') or '.value' in stage
        pct = (st['sum_ms'] / total_ms * 100.0) if total_ms > 0 and not is_value else 0.0
        if pct > max_pct:
            max_pct = pct
            max_stage = stage
    for stage, st in items:
        is_value = stage.endswith('.size') or '.value' in stage
        pct = (st['sum_ms'] / total_ms * 100.0) if total_ms > 0 and not is_value else 0.0
        marker = ' 🔥' if stage == max_stage and not is_value else ''
        pct_str = '   --' if is_value else f'{pct:5.1f}%'
        print(
            f'  {stage:<40} {st["n"]:>8} {_fmt_ms(st["sum_ms"]):>10} {pct_str:>6} '
            f'{_fmt_ms(st["mean_ms"]):>10} {_fmt_ms(st["p95_ms_approx"]):>10} {_fmt_ms(st["max_ms"]):>10}{marker}'
        )


def _cross_role(rolled: dict) -> None:
    """Inf-server forward total vs actor policy_act total → IPC wait estimate."""
    # Sum inf_server.forward across all inf_server procs
    inf_forward_total = 0.0
    actor_policy_total = 0.0
    actor_policy_n = 0
    inf_batched = 0.0
    for (role, _id), agg in rolled.items():
        if role == 'inf_server':
            inf_forward_total += agg.get('inf_server.forward', {}).get('sum_ms', 0.0)
            inf_batched += agg.get('inf_server.batched_forward', {}).get('sum_ms', 0.0)
        elif role == 'actor':
            pol = agg.get('episode_runner.policy_act', {})
            actor_policy_total += pol.get('sum_ms', 0.0)
            actor_policy_n += pol.get('n', 0)
    print('\n=== cross-role correlation ===')
    print(f'  inf_server.forward total              = {_fmt_ms(inf_forward_total)}')
    print(f'  inf_server.batched_forward total      = {_fmt_ms(inf_batched)}')
    print(f'  Σ actor.policy_act total (across N)   = {_fmt_ms(actor_policy_total)} (n={actor_policy_n})')
    if actor_policy_total > 0:
        ipc_wait = max(actor_policy_total - inf_forward_total - inf_batched, 0.0)
        pct_ipc = ipc_wait / actor_policy_total * 100.0
        print(f'  estimated IPC wait per actor.policy   = {_fmt_ms(ipc_wait)} ({pct_ipc:5.1f}% of policy_act)')
    # Batch-size histogram if available
    batch_size_agg = {}
    for (role, _id), agg in rolled.items():
        if role == 'inf_server' and 'inf_server.batch_size' in agg:
            batch_size_agg = agg['inf_server.batch_size']
            break
    if batch_size_agg:
        print(
            '  inf_server.batch_size                 '
            f'mean={batch_size_agg["mean_ms"]:.2f}  max={batch_size_agg["max_ms"]:.0f}  '
            f'n_batches={batch_size_agg["n"]}'
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Aggregate training.core.perf JSONL traces')
    p.add_argument(
        'log_dir',
        nargs='?',
        default='artifacts/_perf_logs',
        help='Directory containing <role>_<id>.jsonl files (default: artifacts/_perf_logs)',
    )
    args = p.parse_args(argv)
    d = Path(args.log_dir)
    if not d.is_dir():
        print(f'error: not a directory: {d}', file=sys.stderr)
        return 2
    by_process = _load_jsonl_dir(d)
    if not by_process:
        print(f'(no jsonl rows found in {d})')
        return 0
    rolled: dict = {}
    for key, rows in by_process.items():
        rolled[key] = _aggregate(rows)
    # Print roles in stable order: pipeline, inf_server, actor
    role_order = {'pipeline': 0, 'inf_server': 1, 'actor': 2}
    for key in sorted(rolled.keys(), key=lambda k: (role_order.get(k[0], 99), k[1])):
        _print_role_table(key[0], key[1], rolled[key])
    _cross_role(rolled)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
