"""Shared fixtures + helpers for the T-12 resume test suite.

Split out of ``test_train_resume.py`` because the resume scope crossed
the 500-line pytest file budget (CLAUDE.md pre-commit hook). The
``_resume_fixtures`` module hosts the cwd-isolation autouse fixture, the
train-step stub fixture, and the three test helpers (``_write_cfg`` /
``_make_args`` / ``_fresh_train`` / ``_make_dummy_ckpt``) that both
test files import. Leading underscore signals "test-internal, not a
runtime helper" per the existing ``tools/runs/tests/`` convention.

The test files are split logically:

- ``test_train_resume.py``        — basic flow / validation / status /
                                    preserved fields / wall_seconds
- ``test_train_resume_versioning.py`` — cfg_resolved_v<N> alloc / parallel
                                    serialization / override / SetupState
                                    shape / Phase B skip-metadata-write
                                    / versioned-filename helper

This module is NOT itself a test file — pytest sees no ``test_``
functions here and so doesn't collect anything from it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from tools.runs import train as train_mod
from tools.runs._train import run as run_mod


@pytest.fixture
def isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repo-root marker + chdir, mirroring other train test files.

    Materialize ``tools/runs/`` under tmp_path so
    ``_verify_repo_root`` accepts the fake cwd; each test gets a
    fresh empty ``artifacts/`` tree.
    """
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def stub_train(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the train step to a no-op — these tests scope to setup +
    metadata + cfg-versioning behavior, not paradigm dispatch.
    """
    monkeypatch.setattr(run_mod, '_run_train_placeholder', lambda _state: None)


def write_cfg(path: Path, run_label: str = 'resume_test', extra: str = '') -> Path:
    """Write a minimal TOML cfg with the given ``meta.run_label``."""
    body = f"""
[meta]
seed = 1
paradigm = "dmc"
run_label = "{run_label}"
"""
    if extra:
        body += '\n' + extra + '\n'
    path.write_text(body)
    return path


def make_args(cfg: Path, *, resume: str | None = None, override: list[str] | None = None) -> Any:
    """Build a Namespace mimicking ``_parse_args`` output."""
    return argparse.Namespace(
        cfg=str(cfg),
        override=list(override or []),
        resume=resume,
    )


def fresh_train(tmp_path: Path, run_label: str = 'resume_test') -> tuple[Path, Path]:
    """Run a fresh ``main()`` train → returns ``(cfg_path, artifacts_dir)``."""
    cfg = write_cfg(tmp_path / 'cfg.toml', run_label)
    rc = train_mod.main([str(cfg)])
    assert rc == 0
    artifacts = tmp_path / 'artifacts'
    run_dirs = [p for p in artifacts.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    return cfg, run_dirs[0]


def make_dummy_ckpt(artifacts_dir: Path, name: str = 'ckpt_30.pt') -> Path:
    """Create ``ckpts/`` subdir + dummy ckpt file.

    Resume Phase A does NOT require the file to be a valid
    ``torch.load`` target — the structural check only requires
    ``ckpts/`` to be a child dir of ``artifacts_dir``. The ckpt itself
    is consumed by ``run_pipeline`` at Phase C; for tests stubbing the
    train step, the ckpt is purely a path-inference handle.
    """
    ckpts = artifacts_dir / 'ckpts'
    ckpts.mkdir(exist_ok=True)
    ckpt = ckpts / name
    ckpt.write_bytes(b'dummy ckpt bytes')
    return ckpt
