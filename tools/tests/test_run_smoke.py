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
