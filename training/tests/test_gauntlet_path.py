"""Path + naming regression tests for ``training.core.gauntlet.dispatch_gauntlet``.

Verifies:
- gauntlet challenger ckpt path is ``<artifacts_dir>/ckpts/gauntlet_g<NNNN>.pt``
  (4-digit zero-pad, no ``ckpt_`` prefix) per spec
  ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
  §ckpts/ naming convention (HIGH-X-1).
- ``<artifacts_dir>/ckpts/`` is auto-created (defensive vs reliance on
  ``CheckpointManager.save`` having already run).
- ``game_marker >= 10_000`` raises (strict 4-digit contract).
- Regression guard: no remaining ``ckpt_gauntlet_`` literal in
  ``training/`` or ``tools/`` (worktree-spawned ``.claude/`` copies +
  ``__pycache__/`` excluded per memory ``feedback_guard_test_rglob_exclude_claude``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from training.core.gauntlet import dispatch_gauntlet
from training.paradigms.az.config import fixed_1v1_config


class _StubChallenger:
    """Mimics the ``save(path: str)`` surface dispatch_gauntlet calls.

    Records the most recent save path so tests can assert on filename
    layout without depending on a real torch checkpoint."""

    def __init__(self) -> None:
        self.saved_paths: list[str] = []

    def save(self, path: str) -> None:
        Path(path).touch()
        self.saved_paths.append(path)


def _noop_log(kind: str, payload: dict) -> None:
    pass


def _run_dispatch(artifacts_dir: Path, game_marker: int) -> _StubChallenger:
    """Drive dispatch_gauntlet through the ``request_eval``-fails path
    so the panel-construction + save side-effect happens deterministically
    without needing a live eval_service socket."""
    cfg = fixed_1v1_config()
    challenger = _StubChallenger()
    with patch('training.core.gauntlet.request_eval', return_value=False):
        dispatch_gauntlet(cfg, challenger, artifacts_dir, game_marker=game_marker, log=_noop_log)
    return challenger


def test_gauntlet_ckpt_first_call_path(tmp_path: Path) -> None:
    challenger = _run_dispatch(tmp_path, game_marker=1)
    assert len(challenger.saved_paths) == 1
    saved = Path(challenger.saved_paths[0])
    expected = tmp_path / 'ckpts' / 'gauntlet_g0001.pt'
    assert saved == expected, f'expected {expected}, got {saved}'
    assert saved.exists()


def test_gauntlet_ckpt_zero_pad_width_4(tmp_path: Path) -> None:
    challenger = _run_dispatch(tmp_path, game_marker=10)
    saved = Path(challenger.saved_paths[0])
    assert saved.name == 'gauntlet_g0010.pt', f'expected 4-digit zero-pad, got {saved.name}'


def test_gauntlet_ckpt_max_boundary(tmp_path: Path) -> None:
    challenger = _run_dispatch(tmp_path, game_marker=9999)
    saved = Path(challenger.saved_paths[0])
    assert saved.name == 'gauntlet_g9999.pt', f'expected boundary gauntlet_g9999.pt, got {saved.name}'


def test_gauntlet_ckpt_overflow_raises(tmp_path: Path) -> None:
    cfg = fixed_1v1_config()
    challenger = _StubChallenger()
    with pytest.raises(ValueError, match='game_marker=10000'):
        dispatch_gauntlet(cfg, challenger, tmp_path, game_marker=10_000, log=_noop_log)
    assert challenger.saved_paths == [], 'overflow path must abort before save'


def test_gauntlet_ckpt_negative_raises(tmp_path: Path) -> None:
    cfg = fixed_1v1_config()
    challenger = _StubChallenger()
    with pytest.raises(ValueError, match='game_marker=-1'):
        dispatch_gauntlet(cfg, challenger, tmp_path, game_marker=-1, log=_noop_log)


def test_gauntlet_ckpts_dir_auto_mkdir(tmp_path: Path) -> None:
    """``ckpts/`` is created even if ``CheckpointManager.save`` has not
    yet run (e.g. gauntlet fires before first train ckpt)."""
    assert not (tmp_path / 'ckpts').exists()
    _run_dispatch(tmp_path, game_marker=42)
    assert (tmp_path / 'ckpts').is_dir()
    assert (tmp_path / 'ckpts' / 'gauntlet_g0042.pt').exists()


def test_gauntlet_artifacts_dir_none_is_noop(tmp_path: Path) -> None:
    cfg = fixed_1v1_config()
    challenger = _StubChallenger()
    dispatch_gauntlet(cfg, challenger, None, game_marker=1, log=_noop_log)
    assert challenger.saved_paths == []


def test_no_old_ckpt_gauntlet_pattern_in_tree() -> None:
    """Regression: the previous ``ckpt_gauntlet_g<N>.pt`` prefix is
    fully removed under ``training/`` + ``tools/``.

    ``.claude/`` worktree spawns + ``__pycache__/`` are excluded to
    avoid false positives from cloned trees (per memory
    ``feedback_guard_test_rglob_exclude_claude``)."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / 'training', repo_root / 'tools']
    offenders: list[Path] = []
    for root in roots:
        for f in root.rglob('*.py'):
            s = str(f)
            if '/.claude/' in s or '/__pycache__/' in s:
                continue
            if f.resolve() == Path(__file__).resolve():
                continue
            text = f.read_text(encoding='utf-8')
            if 'ckpt_gauntlet_' in text:
                offenders.append(f)
    assert not offenders, f'ckpt_gauntlet_ still appears in: {offenders}'
