"""Unit test for tools/debug/watch_run.py::RunState — the live-dashboard
metrics aggregator. Exercises every event kind the aggregator
cares about so that schema drift in metrics.jsonl surfaces as a
test failure, not as a broken dashboard on a running C1.
"""

from __future__ import annotations

from tools.debug.watch_run import RunState


def test_run_state_updates_across_all_event_kinds():
    state = RunState()

    events = [
        {
            'kind': 'selfplay',
            't': 1.0,
            'wall_s': 0.4,
            'stale_gap': 2,
            'winner': 0,
            'n_steps': 12,
        },
        {
            'kind': 'selfplay',
            't': 1.5,
            'wall_s': 0.5,
            'stale_gap': 3,
            'winner': 1,
            'n_steps': 15,
        },
        {'kind': 'train', 't': 2.0, 'value': 0.87, 'policy': 2.3, 'total': 4.5},
        {'kind': 'train', 't': 2.1, 'value': 0.90, 'policy': 2.1, 'total': 4.3},
        {'kind': 'arena', 't': 3.0, 'win_rate': 0.62},
        {'kind': 'replace', 't': 3.1, 'win_rate': 0.62},
        {
            'kind': 'server_stats',
            't': 4.0,
            'batch_mean': 8.5,
            'batch_p50': 8,
            'batch_p95': 12,
            'batch_max': 16,
            'reqs_per_s': 420.0,
            'weight_version': 5,
        },
        {
            'kind': 'system',
            't': 5.0,
            'cpu_pct': 87.0,
            'rss_mb': 2150.5,
            'load1': 3.9,
            'mem_used_gb': 12.0,
        },
        {'kind': 'done', 't': 6.0, 'duration_s': 6.0, 'games': 2},
    ]
    for ev in events:
        state.update(ev)

    assert state.games == 2
    assert state.elapsed == 6.0
    assert state.replaces == 1
    assert state.last_arena_wr == 0.62
    assert state.train_steps_total == 2
    assert state.last_server_stats.get('batch_mean') == 8.5
    assert state.last_cpu == 87.0
    assert state.last_rss_mb == 2150.5
    assert state.done is True

    loss = state.loss_avg()
    assert loss['v'] == (0.87 + 0.90) / 2

    assert state.wall_avg() == (0.4 + 0.5) / 2
    assert state.stale_gap_avg() == (2 + 3) / 2

    line = state.format_line()
    # Spot-check the compact status line's content — the exact
    # formatting is allowed to drift, but every source metric the
    # operator would look at must be somewhere in the line.
    assert 'games=   2' in line
    assert 'wall/g=' in line
    assert 'train=' in line
    assert 'arena=0.62' in line
    assert 'rpl=1' in line
    assert 'batch=' in line
    assert 'cpu=87' in line
    assert 'rss=2150' in line


def test_run_state_diverged_flag():
    state = RunState()
    state.update({'kind': 'train', 't': 0.1, 'value': 0.9, 'policy': 2.0, 'total': 3.0})
    state.update({'kind': 'diverged', 't': 0.2, 'value': 9.0})
    assert state.diverged is True
    assert 'DIVERGED' in state.format_line()
