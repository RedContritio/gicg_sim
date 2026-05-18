"""Path + naming regression tests for ``maybe_arena`` champion ckpt save.

Verifies:
- AZ champion ckpt path is ``<artifacts_dir>/ckpts/champion_g<NNNNN>.pt``
  (5-digit zero-pad, no flat write at run_dir root) per spec
  ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
  §Per-run dir 行 76-96 / §ckpts/ naming 行 606-613
  (``ckpts/`` 含**所有** ``.pt``).
- ``<artifacts_dir>/ckpts/`` is auto-created (defensive vs reliance on
  ``CheckpointManager.save`` having already run; champion can save
  before first train ckpt if arena replacement fires early).
- 5-digit zero-pad preserved (AZ-internal convention, intentionally
  larger than gauntlet's 4-digit — historical OK per T-30 plan).
- ``artifacts_dir=None`` is noop (don't save anywhere).
- Replacement gate: below-threshold arena win-rate doesn't save.
- Regression guard: no remaining flat-root ``champion`` write pattern
  in ``training/`` or ``tools/`` (``.claude/`` + ``__pycache__/``
  excluded per memory ``feedback_guard_test_rglob_exclude_claude``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from training.paradigms.az.arena import ArenaResult
from training.paradigms.az.config import fixed_1v1_config
from training.paradigms.az.train_loop.helpers import maybe_arena
from training.paradigms.az.train_loop.run_result import RunResult


class _StubAgent:
    """Minimal challenger/champion stub.

    - ``save(path)``: records path and touches the file (filename-layout
      tests don't need a real torch ckpt).
    - ``net``: stub with ``state_dict`` / ``load_state_dict`` so the
      replacement branch (``champion.net.load_state_dict(...)``) runs
      cleanly under unittest.mock without touching torch.
    """

    def __init__(self) -> None:
        self.saved_paths: list[str] = []
        self.net = _StubNet()

    def save(self, path: str) -> None:
        Path(path).touch()
        self.saved_paths.append(path)


class _StubNet:
    def state_dict(self) -> dict:
        return {}

    def load_state_dict(self, sd: dict) -> None:
        pass


def _noop_log(kind: str, payload: dict) -> None:
    pass


def _noop_env_factory(i: int):
    raise AssertionError('env_factory should not be called when arena_match is patched')


def _arena_win() -> ArenaResult:
    """Decisive challenger win → triggers replacement + ckpt save."""
    return ArenaResult(challenger_wins=10, champion_wins=0, draws=0, n_games=10)


def _arena_loss() -> ArenaResult:
    """Decisive challenger loss → no replacement, no ckpt save."""
    return ArenaResult(challenger_wins=0, champion_wins=10, draws=0, n_games=10)


def _drive_replace(tmp_path: Path, game_marker: int) -> _StubAgent:
    """Run ``maybe_arena`` with a stubbed arena that forces replacement."""
    cfg = fixed_1v1_config()
    challenger = _StubAgent()
    champion = _StubAgent()
    result = RunResult(n_games_played=0)
    with patch(
        'training.paradigms.az.arena.arena_match',
        return_value=_arena_win(),
    ):
        maybe_arena(
            cfg,
            challenger,
            champion,
            _noop_env_factory,
            game_marker,
            result,
            _noop_log,
            tmp_path,
        )
    return challenger


def test_champion_ckpt_first_call_path(tmp_path: Path) -> None:
    """Champion saved at ``<artifacts_dir>/ckpts/champion_g<NNNNN>.pt``."""
    challenger = _drive_replace(tmp_path, game_marker=1)
    assert len(challenger.saved_paths) == 1
    saved = Path(challenger.saved_paths[0])
    expected = tmp_path / 'ckpts' / 'champion_g00001.pt'
    assert saved == expected, f'expected {expected}, got {saved}'
    assert saved.exists()


def test_champion_ckpt_zero_pad_width_5(tmp_path: Path) -> None:
    """5-digit zero-pad preserved (AZ-internal convention)."""
    challenger = _drive_replace(tmp_path, game_marker=42)
    saved = Path(challenger.saved_paths[0])
    assert saved.name == 'champion_g00042.pt', f'expected 5-digit zero-pad champion_g00042.pt, got {saved.name}'


def test_champion_ckpt_large_game_marker(tmp_path: Path) -> None:
    """5-digit pad accommodates 5-digit game_marker without overflow guard
    (unlike gauntlet T-07's 4-digit strict cap)."""
    challenger = _drive_replace(tmp_path, game_marker=12345)
    saved = Path(challenger.saved_paths[0])
    assert saved.name == 'champion_g12345.pt', f'expected champion_g12345.pt, got {saved.name}'


def test_champion_ckpts_dir_auto_mkdir(tmp_path: Path) -> None:
    """``ckpts/`` is created defensively (champion may save before
    ``CheckpointManager.save`` has run if arena replaces early)."""
    assert not (tmp_path / 'ckpts').exists()
    _drive_replace(tmp_path, game_marker=7)
    assert (tmp_path / 'ckpts').is_dir()
    assert (tmp_path / 'ckpts' / 'champion_g00007.pt').exists()


def test_champion_ckpt_not_at_run_dir_root(tmp_path: Path) -> None:
    """Regression: no flat write at ``<artifacts_dir>/champion_g*.pt``
    (spec 行 608 requires ckpts/ contain all .pt)."""
    _drive_replace(tmp_path, game_marker=3)
    flat_offenders = list(tmp_path.glob('champion_g*.pt'))
    assert flat_offenders == [], f'champion ckpt must NOT be at artifacts_dir root, found: {flat_offenders}'


def test_artifacts_dir_none_is_noop(tmp_path: Path) -> None:
    """``artifacts_dir=None`` → replacement still happens but no save."""
    cfg = fixed_1v1_config()
    challenger = _StubAgent()
    champion = _StubAgent()
    result = RunResult(n_games_played=0)
    with patch(
        'training.paradigms.az.arena.arena_match',
        return_value=_arena_win(),
    ):
        maybe_arena(
            cfg,
            challenger,
            champion,
            _noop_env_factory,
            5,
            result,
            _noop_log,
            None,
        )
    assert challenger.saved_paths == []
    # Replacement still recorded (only the ckpt save is gated by artifacts_dir)
    assert result.champion_replacements == [5]


def test_below_threshold_no_save(tmp_path: Path) -> None:
    """Arena loss (win_rate < threshold) → no replacement, no save."""
    cfg = fixed_1v1_config()
    challenger = _StubAgent()
    champion = _StubAgent()
    result = RunResult(n_games_played=0)
    with patch(
        'training.paradigms.az.arena.arena_match',
        return_value=_arena_loss(),
    ):
        maybe_arena(
            cfg,
            challenger,
            champion,
            _noop_env_factory,
            8,
            result,
            _noop_log,
            tmp_path,
        )
    assert challenger.saved_paths == []
    assert result.champion_replacements == []
    # ckpts/ dir not created when no replacement fires
    assert not (tmp_path / 'ckpts' / 'champion_g00008.pt').exists()


def test_no_old_flat_champion_pattern_in_tree() -> None:
    """Regression: the previous flat ``artifacts_dir / 'champion_g<N>.pt'``
    write pattern is fully removed under ``training/`` + ``tools/``.

    Matches both single-quoted and double-quoted forms with ``artifacts_dir``
    immediately preceding ``champion``.

    ``.claude/`` worktree spawns + ``__pycache__/`` are excluded to
    avoid false positives from cloned trees (per memory
    ``feedback_guard_test_rglob_exclude_claude``)."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / 'training', repo_root / 'tools']
    offenders: list[Path] = []
    self_path = Path(__file__).resolve()
    for root in roots:
        for f in root.rglob('*.py'):
            s = str(f)
            if '/.claude/' in s or '/__pycache__/' in s:
                continue
            if f.resolve() == self_path:
                continue
            text = f.read_text(encoding='utf-8')
            # Old flat-write pattern: artifacts_dir / f'champion...' or similar
            if "artifacts_dir / f'champion" in text or 'artifacts_dir / f"champion' in text:
                offenders.append(f)
    assert not offenders, f'flat champion write pattern still appears in: {offenders}'


def test_no_old_flat_champion_glob_in_tree() -> None:
    """Regression: debug tools no longer glob ``champion_g*.pt`` at
    run_dir root (must look in ``run_dir / 'ckpts'``).

    Pattern matched: ``run_dir.glob('champion`` (i.e. globbing directly
    on the run dir, not on its ``ckpts/`` subdir)."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / 'training', repo_root / 'tools']
    offenders: list[Path] = []
    self_path = Path(__file__).resolve()
    for root in roots:
        for f in root.rglob('*.py'):
            s = str(f)
            if '/.claude/' in s or '/__pycache__/' in s:
                continue
            if f.resolve() == self_path:
                continue
            text = f.read_text(encoding='utf-8')
            if "run_dir.glob('champion" in text or 'run_dir.glob("champion' in text:
                offenders.append(f)
    assert not offenders, (
        f'flat run_dir.glob("champion_g*.pt") still appears in: {offenders} (must use (run_dir / "ckpts").glob(...))'
    )
