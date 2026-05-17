"""Smoke tests for `tools.run` entry."""

from __future__ import annotations

from tools import run as tools_run


def test_run_rejects_run_id_and_run_label_override_conflict(tmp_path, capsys):
    """AD4: --run-id pins cfg_run_label snapshot in metadata; allowing
    a runtime --override meta.run_label would silently desync the
    metadata.cfg_run_label from the actual artifacts dir suffix. Reject
    with a clear hint to use register's --cfg-run-label-override."""
    p = tmp_path / 'cfg.toml'
    p.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "x"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    rc = tools_run.main(
        [
            str(p),
            '--run-id',
            's999',
            '--override',
            'meta.run_label=s999_x',
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert 'conflict' in err.lower() or 'cfg-run-label-override' in err


def test_run_accepts_run_id_alone_without_conflict_check(tmp_path, capsys):
    """Bilateral coverage of the AD4 conflict check: `--run-id` ALONE
    must NOT trigger the conflict path (it should fall through to the
    later run-not-registered check). Catches future inverted-condition
    regressions where the check would fire on `--run-id` alone."""
    p = tmp_path / 'cfg.toml'
    p.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "x"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    rc = tools_run.main([str(p), '--run-id', 's999'])
    # Will rc==2 from "run not registered" later, but NOT from the
    # conflict path — assert stderr proves we didn't hit the conflict.
    err = capsys.readouterr().err
    assert 'conflicts with --run-id' not in err


def test_run_accepts_run_label_override_alone_without_conflict_check(tmp_path, capsys):
    """Bilateral coverage of the AD4 conflict check: `--override meta.run_label=`
    ALONE (no `--run-id`) must NOT trigger the conflict path. The cfg here
    is intentionally minimal — load_cfg will raise later for missing seed,
    but that's downstream of the conflict check we want to verify."""
    p = tmp_path / 'cfg.toml'
    p.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "x"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    try:
        tools_run.main([str(p), '--override', 'meta.run_label=anything'])
    except Exception:
        pass  # downstream cfg validation may raise — irrelevant
    err = capsys.readouterr().err
    assert 'conflicts with --run-id' not in err


def test_metadata_timestamp_to_dir_prefix_uses_utc_always():
    """HIGH 1: dir-name prefix must be UTC (cross-host consistent),
    NOT local tz — otherwise register on host A (UTC+8) + train on
    host B (UTC-5) yield different dir prefixes for the same run."""
    from tools.run import _metadata_timestamp_to_dir_prefix

    # UTC iso → UTC strftime
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21+00:00') == '202605171844'
    # Non-UTC iso (e.g. registered on UTC+8 host) → still UTC strftime
    # 18:44 +08:00 = 10:44 UTC
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21+08:00') == '202605171044'
    # UTC-5 → 23:44 UTC
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21-05:00') == '202605172344'


def test_run_auto_completes_artifacts_dir_on_success(tmp_path, monkeypatch):
    """M3 / C2 闭环: --run-id + successful train must update
    metadata.artifacts_dir + status='done' WITHOUT user manually
    invoking `tools.runs.complete --artifacts-dir`."""
    from pathlib import Path

    from tools.runs import register, schema

    # Locate repo root (worktree-compatible) to absolute-path `data_dir`
    # and the cfg file — test does monkeypatch.chdir(tmp_path) so the
    # default relative `data_dir = "data"` would resolve under tmp_path
    # and miss the actual data tree.
    here = Path(__file__).resolve()
    repo_root = next(p for p in here.parents if (p / 'gicg_engine').is_dir() and (p / 'tools').is_dir())
    data_dir_abs = repo_root / 'data'

    cfg = tmp_path / 's999_cfg.toml'
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "auto_complete_smoke"\n'
        'seed = 42\ndevice = "cpu"\n'
        '[pipeline]\nmode = "serial"\nnum_actors = 1\n'
        '[scenario]\nteam_0 = ["赤蝶"]\nteam_1 = ["墨客"]\nteam_size = 1\n'
        'max_rounds = 5\ndeck_padding = { card = "碌碌无为", target_size = 15 }\n'
        'pool = ["v_legacy", "test_basic"]\n'
        f'data_dir = "{data_dir_abs}"\n'
        '[paradigm.dmc]\nversion = "1.0.0"\nparadigm = "dmc"\n'
        'epsilon = 0.05\ngamma = 1.0\nlr = 1e-4\nweight_decay = 0.0\n'
        'batch_size = 16\nmax_grad_norm = 5.0\nbuffer_cap = 1000\n'
        'max_game_steps = 30\ntotal_frames = 100\ntrain_ratio = 4\n'
        'eval_interval_episodes = 30\neval_n_scenarios = 8\n'
        'eval_baselines = ["F1-D2"]\n'
        '[paradigm.dmc.agent]\nd_model = 32\nn_cross_layers = 1\ndropout = 0.0\n'
        '[paradigm.dmc.opponent_mix]\nrandom = 1.0\nf1d2 = 0.0\nf1d4 = 0.0\n'
        'historical = 0.0\nring_size = 5\n'
        '[checkpoint]\nsave_every = 500\nkeep_last_n = 1\n'
        f'artifacts_root = "{tmp_path}/artifacts"\n',
        encoding='utf-8',
    )
    register.register(
        run_id='s999',
        cfg_file=str(cfg),
        root=tmp_path,
        host='test-host',
        git_commit='deadbeef',
    )

    monkeypatch.chdir(tmp_path)
    rc = tools_run.main([str(cfg), '--run-id', 's999', '--max-steps', '3'])
    assert rc == 0

    meta = schema.load_file(schema.run_path('s999', root=tmp_path))
    assert meta.status == 'done'
    assert meta.artifacts_dir.startswith('artifacts/')
    # H3 invariant: artifacts_dir must be repo-relative (cross-host portability)
    assert not Path(meta.artifacts_dir).is_absolute()
    assert (tmp_path / meta.artifacts_dir / 'latest.pt').exists()


def test_run_auto_completes_status_failed_on_error(tmp_path, monkeypatch):
    """M3 / C2 闭环 failure path: --run-id + train exception must still
    update metadata.status='failed' via the finally block before the
    exception re-raises. Covers the `except BaseException: auto_status =
    'failed'; raise` branch left uncovered by the success-path test."""
    from pathlib import Path

    from tools.runs import register, schema

    here = Path(__file__).resolve()
    repo_root = next(p for p in here.parents if (p / 'gicg_engine').is_dir() and (p / 'tools').is_dir())
    data_dir_abs = repo_root / 'data'

    cfg = tmp_path / 's998_cfg.toml'
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "fail_smoke"\n'
        'seed = 42\ndevice = "cpu"\n'
        '[pipeline]\nmode = "serial"\nnum_actors = 1\n'
        '[scenario]\nteam_0 = ["赤蝶"]\nteam_1 = ["墨客"]\nteam_size = 1\n'
        'max_rounds = 5\ndeck_padding = { card = "碌碌无为", target_size = 15 }\n'
        'pool = ["v_legacy", "test_basic"]\n'
        f'data_dir = "{data_dir_abs}"\n'
        '[paradigm.dmc]\nversion = "1.0.0"\nparadigm = "dmc"\n'
        'epsilon = 0.05\ngamma = 1.0\nlr = 1e-4\nweight_decay = 0.0\n'
        'batch_size = 16\nmax_grad_norm = 5.0\nbuffer_cap = 1000\n'
        'max_game_steps = 30\ntotal_frames = 100\ntrain_ratio = 4\n'
        'eval_interval_episodes = 30\neval_n_scenarios = 8\n'
        'eval_baselines = ["F1-D2"]\n'
        '[paradigm.dmc.agent]\nd_model = 32\nn_cross_layers = 1\ndropout = 0.0\n'
        '[paradigm.dmc.opponent_mix]\nrandom = 1.0\nf1d2 = 0.0\nf1d4 = 0.0\n'
        'historical = 0.0\nring_size = 5\n'
        '[checkpoint]\nsave_every = 500\nkeep_last_n = 1\n'
        f'artifacts_root = "{tmp_path}/artifacts"\n',
        encoding='utf-8',
    )
    register.register(
        run_id='s998',
        cfg_file=str(cfg),
        root=tmp_path,
        host='test-host',
        git_commit='deadbeef',
    )

    # Force run_pipeline to raise — finally block must still auto-complete.
    import tools.run as tools_run_mod

    def _explode(*a, **kw):
        raise RuntimeError('synthetic-train-failure')

    monkeypatch.setattr(tools_run_mod, 'run_pipeline', _explode)
    monkeypatch.chdir(tmp_path)

    import pytest

    with pytest.raises(RuntimeError, match='synthetic-train-failure'):
        tools_run.main([str(cfg), '--run-id', 's998', '--max-steps', '3'])

    meta = schema.load_file(schema.run_path('s998', root=tmp_path))
    assert meta.status == 'failed'
    assert meta.artifacts_dir.startswith('artifacts/')
    assert not Path(meta.artifacts_dir).is_absolute()


def test_run_rejects_cfg_drift_checksum(tmp_path, capsys):
    """HIGH 2 (round-3 review): register pins cfg_checksum;tools.run --run-id
    must reject if user edited cfg between register and train (silent drift
    would defeat C2 snapshot intent)."""
    from pathlib import Path

    from tools.runs import register

    cfg = tmp_path / 's997_cfg.toml'
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "drift_test"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    register.register(
        run_id='s997',
        cfg_file=str(cfg),
        root=tmp_path,
        host='h',
        git_commit='abc',
    )
    # Edit cfg AFTER register (add a trivial line) → checksum changes.
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "drift_test"\n[paradigm.dmc]\nepsilon = 0.1\n',
        encoding='utf-8',
    )

    # Monkeypatch runs_dir to point at tmp_path so tools.run finds s997.
    import tools.runs.schema as runs_schema

    original_runs_dir = runs_schema.runs_dir
    runs_schema.runs_dir = lambda root=None: original_runs_dir(tmp_path) if root is None else original_runs_dir(root)
    try:
        rc = tools_run.main([str(cfg), '--run-id', 's997'])
    finally:
        runs_schema.runs_dir = original_runs_dir
    assert rc == 2
    err = capsys.readouterr().err
    assert 'cfg drift' in err
    assert 'checksum' in err


def test_run_rejects_cfg_drift_run_label(tmp_path, capsys):
    """HIGH 2: same drift guard for cfg.meta.run_label."""
    from tools.runs import register

    cfg = tmp_path / 's996_cfg.toml'
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "label_v1"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    register.register(
        run_id='s996',
        cfg_file=str(cfg),
        root=tmp_path,
        host='h',
        git_commit='abc',
    )
    # Edit cfg's run_label only (same logical structure but different label).
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "label_v2"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )

    import tools.runs.schema as runs_schema

    original_runs_dir = runs_schema.runs_dir
    runs_schema.runs_dir = lambda root=None: original_runs_dir(tmp_path) if root is None else original_runs_dir(root)
    try:
        rc = tools_run.main([str(cfg), '--run-id', 's996'])
    finally:
        runs_schema.runs_dir = original_runs_dir
    assert rc == 2
    err = capsys.readouterr().err
    assert 'cfg drift' in err
    assert 'run_label' in err
