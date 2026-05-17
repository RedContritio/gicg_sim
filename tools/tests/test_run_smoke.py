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
