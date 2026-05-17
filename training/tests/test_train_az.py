"""Smoke test for the full AZ training loop.

Instantiates the tiny ``smoke_config`` preset (3 games, MCTS 8
rollouts, no arena, no gauntlet) and verifies the loop runs end to
end without crashing. Not a functional verification — the network
is not expected to learn anything useful in 3 games — this is
purely a "does the pipeline wire up correctly" smoke.

For functional verification see step 7 (C1 run).
"""

from __future__ import annotations

import os

import pytest

from training.paradigms.az.config import smoke_config
from training.paradigms.az.train_az import RunResult, train_az

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def test_smoke_runs_end_to_end():
    cfg = smoke_config(data_dir=DATA_DIR)
    result = train_az(cfg)

    assert isinstance(result, RunResult)
    assert result.n_games_played == cfg.n_games
    assert result.artifacts_dir is None  # write_artifacts=False

    # Every game reported a winner and step count
    assert len(result.selfplay_winners) == cfg.n_games
    assert len(result.selfplay_n_steps) == cfg.n_games
    for n in result.selfplay_n_steps:
        assert n > 0, 'self-play game produced 0 steps'
    for w in result.selfplay_winners:
        assert w in (0, 1, 2), f'unexpected winner code: {w}'

    # Smoke runs with n_games=3 and min_buffer_before_train=8, so the
    # first game's short trajectory may not fill the buffer. But
    # across 3 games we should have triggered at least ONE training
    # iteration (unless games are abnormally short).
    assert len(result.training_stats) > 0, (
        f'smoke produced no training stats — buffer never reached min_buffer_before_train={cfg.min_buffer_before_train}'
    )

    # Every training stat is finite
    for s in result.training_stats:
        for k in ('total', 'value', 'policy', 'l2'):
            v = s[k]
            assert v == v, f'{k} is NaN'  # NaN != NaN
            assert abs(v) < 1e6, f'{k} = {v} is unreasonable'

    # Arena / gauntlet disabled by smoke
    assert len(result.arena_results) == 0
    assert len(result.gauntlet_results) == 0


def test_metrics_jsonl_has_timestamps_and_new_fields(tmp_path):
    """Run a tiny smoke with artifacts enabled and verify every line
    in metrics.jsonl carries a ``t`` field and that ``selfplay``
    events include the new ``wall_s`` / ``weight_version`` /
    ``stale_gap`` fields."""
    import json

    cfg = smoke_config(data_dir=DATA_DIR)
    cfg.write_artifacts = True
    cfg.artifacts_root = str(tmp_path)
    train_az(cfg)

    art_dirs = list(tmp_path.iterdir())
    assert len(art_dirs) == 1, f'expected 1 artifacts dir, got {art_dirs}'
    metrics_path = art_dirs[0] / 'metrics.jsonl'
    assert metrics_path.exists()

    events = []
    with open(metrics_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))

    assert len(events) > 0
    for ev in events:
        assert 't' in ev, f'event missing ``t``: {ev}'
        assert isinstance(ev['t'], (int, float))
        assert ev['t'] >= 0

    selfplay_events = [e for e in events if e['kind'] == 'selfplay']
    assert len(selfplay_events) > 0
    for ev in selfplay_events:
        for key in ('wall_s', 'weight_version', 'stale_gap'):
            assert key in ev, f'selfplay event missing {key}: {ev}'


def test_stats_and_system_events_appear(tmp_path):
    """With short emit intervals, a normal smoke run must produce at
    least one ``server_stats`` event from the inference server and
    at least one ``system`` snapshot event from the background
    monitor thread. Without this, regressions in either telemetry
    path would go silent until the operator noticed missing data in
    a 6-hour C1 run."""
    import json

    cfg = smoke_config(data_dir=DATA_DIR)
    cfg.write_artifacts = True
    cfg.artifacts_root = str(tmp_path)
    # Tighten both telemetry intervals so even a ~3 s smoke produces
    # at least one event of each kind.
    cfg.inference.stats_emit_interval_s = 0.1
    cfg.sysmon_interval_s = 0.1
    train_az(cfg)

    run_dir = next(iter(tmp_path.iterdir()))
    metrics_path = run_dir / 'metrics.jsonl'
    kinds = set()
    stats_events = []
    for line in open(metrics_path):
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        kinds.add(ev['kind'])
        if ev['kind'] == 'server_stats':
            stats_events.append(ev)

    assert 'server_stats' in kinds, 'no server_stats event emitted — inference server telemetry path is broken'
    assert 'system' in kinds, (
        'no system event emitted — system monitor thread is not producing (psutil missing? loop broken?)'
    )
    # server_stats events must carry the batch-statistics fields.
    for ev in stats_events:
        for key in ('batch_mean', 'batch_p95', 'reqs_per_s', 'weight_version'):
            assert key in ev, f'server_stats missing {key}: {ev}'


def test_smoke_config_arena_enabled():
    """Tiny variant that enables arena and verifies the replace path
    runs (not necessarily triggers — with random-init nets the win
    rate is ~50%, may or may not cross the 55% threshold)."""
    cfg = smoke_config(data_dir=DATA_DIR)
    cfg.games_per_arena = 2
    cfg.arena_games = 4
    cfg.n_games = 2
    result = train_az(cfg)
    # 1 arena fire at game 2
    assert len(result.arena_results) == 1
    g_idx, arena = result.arena_results[0]
    assert g_idx == 2
    assert arena.n_games == 4
    assert 0.0 <= arena.challenger_win_rate <= 1.0


def test_smoke_config_zero_arena_skips():
    """games_per_arena=0 disables the arena branch entirely."""
    cfg = smoke_config(data_dir=DATA_DIR)
    cfg.games_per_arena = 0
    cfg.n_games = 2
    result = train_az(cfg)
    assert len(result.arena_results) == 0
