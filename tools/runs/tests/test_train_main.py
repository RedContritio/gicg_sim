"""Tests for tools.runs.train ``main()`` + argparse glue.

Split out of ``test_train_setup.py`` (T-09 quality-review I-1 follow-up
— the setup test file crossed the 500-line budget after Phase B
landed). Phase-A-only unit tests stay in ``test_train_setup.py``;
anything that exercises ``main()`` (which dispatches Phase A → B → C as
phases land) lives here so the file budget tracks logical scope.

Covered surface (T-10 baseline):

- ``main()`` happy path — Phase A + B + C all succeed, returns 0
- ``main()`` exit 2 on bad ``run_label`` (Phase A regex reject)
- ``main()`` exit 2 on missing cfg file (Phase A pre-resolve guard)
- ``_parse_args`` — ``--resume`` flag parses (T-12 implements logic)
- ``_parse_args`` — ``--override`` repeatable, default empty list

Phase C close-metadata behavior (read-and-compare, exit codes 1/3,
external mark detection, SystemExit propagation) is covered by
``test_train_close.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.runs import train as train_mod
from tools.runs._train import run as run_mod


# --- Fixtures (mirror test_train_setup.py to keep tests hermetic) -------------


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialize ``tools/runs/`` under tmp_path so ``_verify_repo_root``
    accepts the fake cwd, then chdir there. Each test gets a fresh
    ``artifacts/`` tree.
    """
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _stub_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rationale as the test_train_close.py stub fixture: the T-11
    placeholder is a real paradigm dispatch shim; this file's minimal
    cfgs (``[meta]``-only) would fail dispatch validate. Stub back to a
    no-op so main() integration scope here stays "argparse + Phase A/B/C
    glue", not "5-paradigm end-to-end". The 5-paradigm e2e lives in
    test_train_dispatch_smoke.py.
    """
    monkeypatch.setattr(run_mod, '_run_train_placeholder', lambda _state: None)


def _write_cfg(path: Path, run_label: str) -> Path:
    """Minimal TOML cfg sufficient for Phase A regex check + resolve."""
    path.write_text(f"""
[meta]
seed = 1
paradigm = "dmc"
run_label = "{run_label}"
""")
    return path


# --- main() integration -------------------------------------------------------


def test_main_succeeds_and_returns_0(tmp_path: Path) -> None:
    """End-to-end: Phase A + B + C all green.

    Post T-10, Phase C is a no-op stub (``_run_train_placeholder``) so
    the close path runs cleanly and ``main()`` returns exit 0 with a
    fully-closed metadata.toml. T-11 will replace the stub with real
    paradigm dispatch; this test still passes as long as the placeholder
    does not raise.
    """
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'main_test')
    rc = train_mod.main([str(cfg)])
    assert rc == 0


def test_main_returns_2_on_bad_label(tmp_path: Path) -> None:
    """Phase A regex reject → exit 2 (cfg / setup error)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', '../etc')
    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(cfg)])
    assert ei.value.code == 2


def test_main_returns_2_on_missing_cfg(tmp_path: Path) -> None:
    """Phase A pre-resolve guard fires before any artifacts mkdir."""
    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(tmp_path / 'missing.toml')])
    assert ei.value.code == 2


# --- argparse glue ------------------------------------------------------------


def test_parse_args_supports_resume_flag(tmp_path: Path) -> None:
    """``--resume`` is parsed (logic lands in T-12)."""
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text('# placeholder\n')
    args = train_mod._parse_args([str(cfg), '--resume', '/tmp/some.pt'])
    assert args.resume == '/tmp/some.pt'


def test_parse_args_override_repeatable(tmp_path: Path) -> None:
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text('# placeholder\n')
    args = train_mod._parse_args([str(cfg), '--override', 'a.b=1', '--override', 'c.d=2'])
    assert args.override == ['a.b=1', 'c.d=2']


def test_parse_args_override_default_empty(tmp_path: Path) -> None:
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text('# placeholder\n')
    args = train_mod._parse_args([str(cfg)])
    assert args.override == []
    assert args.resume is None
