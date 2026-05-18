"""Tests for ``tools.runs.recover`` (T-17 clean-slate redesign).

Covers spec §CLI recover 细则 HIGH-4-C 行 137-143 + §Status 状态机 unknown
仅 recover 写入 行 142, 183 + §Per-run 完全 self-contained 行 76-96.

Spec contracts under test:

- Entry condition: ``<dir>/metadata.toml`` missing + ``cfg_resolved*.toml``
  present → recover synthesises ``status='unknown'`` metadata.
- ``cfg_resolved_version`` is the **highest** version found
  (``cfg_resolved.toml`` → 1; ``cfg_resolved_v<N>.toml`` → N).
- Refuse to overwrite an existing ``metadata.toml`` (FileExistsError).
- Refuse to recover a dir with no ``cfg_resolved*.toml`` (FileNotFoundError).
- Refuse non-existent / non-directory paths (ValueError).
- Refuse dirs that don't match ``<ts>_<NNN>_<label>`` regex (ValueError).
- ``status='unknown'`` flows through ``list`` and is markable to
  ``{done, failed, killed}`` (spec 行 229 — unknown is a non-terminal
  source state).
- ``notes`` field carries the audit-trail sentinel
  ``'recovered via tools.runs.recover'``.
- CLI: exit 0 on success, 2 on every failure mode.

Fixtures build a partial-recovery dir state (cfg + ckpts present,
metadata.toml absent) the same way T-08 train.py would have laid them
down before crashing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import list as list_cmd
from tools.runs import mark as mark_cmd
from tools.runs import recover as recover_cmd
from tools.runs import schema


# --- Fixture builder --------------------------------------------------------


def _build_partial_dir(
    repo_root: Path,
    *,
    nnn: str,
    label: str = 'probe',
    timestamp_compact: str = '202605180355',
    cfg_versions: tuple[int, ...] = (1,),
    paradigm: str | None = 'az',
    ckpt_steps: tuple[int, ...] = (30,),
    write_metadata: bool = False,
) -> Path:
    """Lay down a per-run dir mimicking the post-crash state recover handles.

    - ``cfg_versions``: which ``cfg_resolved*.toml`` versions to create
      (1 → ``cfg_resolved.toml``; N>=2 → ``cfg_resolved_v<N>.toml``).
      Empty tuple → no cfg snapshot at all (forces the missing-cfg
      error path).
    - ``paradigm``: written into every ``cfg_resolved*.toml`` ``[meta]``
      section. ``None`` → empty ``[meta]`` (paradigm derivation falls
      back to ``'?'`` in ``list``).
    - ``ckpt_steps``: which ``ckpts/ckpt_<step>.pt`` files to create
      (zero-byte; recover does not inspect their contents). Empty tuple
      → no ``ckpts/`` directory.
    - ``write_metadata``: if True, also lay down a valid metadata.toml
      (tests the ``FileExistsError`` clobber-guard path).

    Returns the created run dir path.
    """
    run_dir = repo_root / 'artifacts' / f'{timestamp_compact}_{nnn}_{label}'
    run_dir.mkdir(parents=True)

    for version in cfg_versions:
        if version == 1:
            fname = 'cfg_resolved.toml'
        else:
            fname = f'cfg_resolved_v{version}.toml'
        body = '[meta]\n'
        if paradigm is not None:
            body += f'paradigm = "{paradigm}"\n'
        body += f'run_label = "{label}"\n'
        (run_dir / fname).write_text(body, encoding='utf-8')

        # cfg_leaf snapshot is part of the per-run dir contract (spec 行
        # 82) but recover does not require it; lay it down only when
        # cfg_resolved is also present so the test fixture mirrors the
        # actual production write order.
        if version == 1:
            leaf_name = 'cfg_leaf.toml'
        else:
            leaf_name = f'cfg_leaf_v{version}.toml'
        (run_dir / leaf_name).write_text(body, encoding='utf-8')

    if ckpt_steps:
        ckpts_dir = run_dir / 'ckpts'
        ckpts_dir.mkdir()
        for step in ckpt_steps:
            (ckpts_dir / f'ckpt_{step}.pt').write_bytes(b'')

    if write_metadata:
        meta = schema.RunMetadata(
            run_id=nnn,
            timestamp='2026-05-18T03:55:00+00:00',
            cfg_file=f'configs/{label}.toml',
            cfg_resolved_version=max(cfg_versions) if cfg_versions else 1,
            git_commit='abc1234',
            host='test-host',
            status='done',
            artifacts_dir=f'artifacts/{timestamp_compact}_{nnn}_{label}',
            wall_seconds=42.5,
            exit_code=0,
            notes='original',
        )
        (run_dir / 'metadata.toml').write_text(schema.dumps(meta), encoding='utf-8')

    return run_dir


# --- Basic recover (happy path) ---------------------------------------------


class TestBasicRecover:
    def test_recover_creates_metadata_toml(self, tmp_path: Path) -> None:
        """Smoke: missing metadata.toml + v1 cfg → recover writes file."""
        run_dir = _build_partial_dir(tmp_path, nnn='000069')
        assert not (run_dir / 'metadata.toml').exists()
        recover_cmd.recover_metadata(tmp_path, run_dir)
        assert (run_dir / 'metadata.toml').is_file()

    def test_status_is_unknown(self, tmp_path: Path) -> None:
        """Spec 行 142, 183 — recover is the **only** writer of 'unknown'."""
        run_dir = _build_partial_dir(tmp_path, nnn='000069')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.status == 'unknown'
        # Round-trip via load_file: schema validation must accept it
        on_disk = schema.load_file(run_dir / 'metadata.toml')
        assert on_disk.status == 'unknown'

    def test_run_id_from_dir_name(self, tmp_path: Path) -> None:
        """``run_id`` is parsed from the 6-digit segment of the dir name."""
        run_dir = _build_partial_dir(tmp_path, nnn='000042')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.run_id == '000042'

    def test_timestamp_from_dir_name(self, tmp_path: Path) -> None:
        """``timestamp`` is derived from the 12-digit dir prefix (UTC iso8601)."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', timestamp_compact='202605180355')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        # Must be UTC iso8601 matching the dir-name prefix exactly.
        assert meta.timestamp == '2026-05-18T03:55:00+00:00'

    def test_v1_cfg_yields_version_1(self, tmp_path: Path) -> None:
        """Only ``cfg_resolved.toml`` (no suffix) → version=1."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(1,))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 1

    def test_cfg_file_is_recovered_sentinel(self, tmp_path: Path) -> None:
        """``cfg_file`` (last leaf path) is unknowable retroactively."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_file == '<unknown — recovered>'

    def test_git_commit_is_unknown(self, tmp_path: Path) -> None:
        """``git_commit`` cannot be reconstructed from on-disk state."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.git_commit == 'unknown'

    def test_wall_seconds_zero(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.wall_seconds == 0.0

    def test_exit_code_zero(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.exit_code == 0

    def test_notes_audit_trail(self, tmp_path: Path) -> None:
        """``notes`` records the rescue origin so downstream ``show`` / ``mark``
        operators know the metadata is synthesised, not original."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.notes == 'recovered via tools.runs.recover'

    def test_artifacts_dir_repo_relative(self, tmp_path: Path) -> None:
        """``artifacts_dir`` is repo-relative POSIX form (R1 normalize)."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.artifacts_dir == f'artifacts/{run_dir.name}'

    def test_host_is_current_machine(self, tmp_path: Path) -> None:
        """``host`` is the recover-time machine (not the original train host
        — which is unknowable; spec accepts this drift)."""
        import socket as _socket  # noqa: PLC0415 — fixture-local import

        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.host == _socket.gethostname()


# --- cfg_resolved versioning (highest is truth) -----------------------------


class TestCfgResolvedVersioning:
    def test_v1_only(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(1,))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 1

    def test_v1_v2_v3_yields_3(self, tmp_path: Path) -> None:
        """Spec 行 157 — highest version is current truth."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(1, 2, 3))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 3

    def test_v1_v2_yields_2(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(1, 2))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 2

    def test_only_v2_no_v1_still_picks_v2(self, tmp_path: Path) -> None:
        """Degenerate (production never produces this, but recover must not
        crash if a partial sync left v2 without v1 — picks the highest
        present)."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(2,))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 2

    def test_v1_v5_v3_picks_v5(self, tmp_path: Path) -> None:
        """Non-contiguous versions still pick numerical max."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=(1, 3, 5))
        meta = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta.cfg_resolved_version == 5


# --- Error paths ------------------------------------------------------------


class TestErrorPaths:
    def test_existing_metadata_raises(self, tmp_path: Path) -> None:
        """Spec 行 139 — recover refuses to clobber existing metadata."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', write_metadata=True)
        assert (run_dir / 'metadata.toml').exists()
        with pytest.raises(FileExistsError, match='already exists'):
            recover_cmd.recover_metadata(tmp_path, run_dir)

    def test_existing_metadata_not_modified_on_raise(self, tmp_path: Path) -> None:
        """The clobber-guard must leave the original metadata byte-for-byte."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', write_metadata=True)
        before = (run_dir / 'metadata.toml').read_bytes()
        with pytest.raises(FileExistsError):
            recover_cmd.recover_metadata(tmp_path, run_dir)
        after = (run_dir / 'metadata.toml').read_bytes()
        assert before == after

    def test_no_cfg_resolved_raises(self, tmp_path: Path) -> None:
        """No ``cfg_resolved*.toml`` → cannot derive version → raise."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=())
        with pytest.raises(FileNotFoundError, match='no cfg_resolved'):
            recover_cmd.recover_metadata(tmp_path, run_dir)

    def test_dir_does_not_exist_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='not a directory'):
            recover_cmd.recover_metadata(tmp_path, tmp_path / 'artifacts' / 'ghost_dir')

    def test_path_is_file_raises(self, tmp_path: Path) -> None:
        """Recover refuses to operate on a regular file (not a dir)."""
        not_a_dir = tmp_path / 'artifacts' / '202605180355_000001_label'
        not_a_dir.parent.mkdir(parents=True)
        not_a_dir.write_text('regular file', encoding='utf-8')
        with pytest.raises(ValueError, match='not a directory'):
            recover_cmd.recover_metadata(tmp_path, not_a_dir)

    def test_dir_name_invalid_shape_raises(self, tmp_path: Path) -> None:
        """Dirs not matching ``<ts>_<NNN>_<label>`` cannot yield run_id."""
        bad_dir = tmp_path / 'artifacts' / 'legacy_run_pre_redesign'
        bad_dir.mkdir(parents=True)
        (bad_dir / 'cfg_resolved.toml').write_text('[meta]\nparadigm = "az"\n', encoding='utf-8')
        with pytest.raises(ValueError, match='does not match'):
            recover_cmd.recover_metadata(tmp_path, bad_dir)

    def test_dir_outside_repo_raises(self, tmp_path: Path) -> None:
        """``normalize_repo_relative`` rejects dirs outside ``repo_root``."""
        other_root = tmp_path / 'elsewhere'
        run_dir = _build_partial_dir(other_root, nnn='000001')
        repo_root = tmp_path / 'repo'
        repo_root.mkdir()
        with pytest.raises(ValueError, match='outside repo root'):
            recover_cmd.recover_metadata(repo_root, run_dir)


# --- Integration with list / mark (post-recover lifecycle) -----------------


class TestPostRecoverLifecycle:
    def test_list_shows_recovered_run(self, tmp_path: Path) -> None:
        """Recovered run is immediately visible to ``list_runs``."""
        run_dir = _build_partial_dir(tmp_path, nnn='000069')
        recover_cmd.recover_metadata(tmp_path, run_dir)
        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].nnn == '000069'
        assert rows[0].status == 'unknown'

    def test_list_filter_unknown_picks_only_recovered(self, tmp_path: Path) -> None:
        """``list --status unknown`` filters to recovered runs."""
        # One recovered (unknown), one normal (done).
        run_a = _build_partial_dir(tmp_path, nnn='000001', timestamp_compact='202605180300')
        recover_cmd.recover_metadata(tmp_path, run_a)

        run_b = _build_partial_dir(tmp_path, nnn='000002', timestamp_compact='202605180400', write_metadata=True)
        # ``run_b`` already has metadata.toml from fixture (status=done).
        _ = run_b

        rows = list_cmd.list_runs(tmp_path, status_filter='unknown')
        assert len(rows) == 1
        assert rows[0].nnn == '000001'

    def test_mark_unknown_to_killed_succeeds(self, tmp_path: Path) -> None:
        """``unknown → killed`` is the canonical post-recover transition
        (spec 行 229 + 142-143)."""
        run_dir = _build_partial_dir(tmp_path, nnn='000069')
        recover_cmd.recover_metadata(tmp_path, run_dir)

        mark_cmd.mark_run(tmp_path, '69', 'killed', 'recovered')
        meta = schema.load_file(run_dir / 'metadata.toml')
        assert meta.status == 'killed'
        assert meta.notes == 'recovered'

    def test_mark_unknown_to_done_succeeds(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000070')
        recover_cmd.recover_metadata(tmp_path, run_dir)

        mark_cmd.mark_run(tmp_path, '70', 'done', None)
        meta = schema.load_file(run_dir / 'metadata.toml')
        assert meta.status == 'done'
        # Default notes preservation: recovered audit-trail carries over.
        assert meta.notes == 'recovered via tools.runs.recover'

    def test_mark_unknown_to_failed_succeeds(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000071')
        recover_cmd.recover_metadata(tmp_path, run_dir)

        mark_cmd.mark_run(tmp_path, '71', 'failed', None)
        meta = schema.load_file(run_dir / 'metadata.toml')
        assert meta.status == 'failed'


# --- CLI integration -------------------------------------------------------


class TestCLI:
    def test_cli_main_exits_0_on_success(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        rc = recover_cmd.main([str(run_dir), '--root', str(tmp_path)])
        assert rc == 0
        assert (run_dir / 'metadata.toml').is_file()

    def test_cli_main_exits_2_on_existing_metadata(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001', write_metadata=True)
        rc = recover_cmd.main([str(run_dir), '--root', str(tmp_path)])
        assert rc == 2

    def test_cli_main_exits_2_on_missing_cfg(self, tmp_path: Path) -> None:
        run_dir = _build_partial_dir(tmp_path, nnn='000001', cfg_versions=())
        rc = recover_cmd.main([str(run_dir), '--root', str(tmp_path)])
        assert rc == 2

    def test_cli_main_exits_2_on_nonexistent_dir(self, tmp_path: Path) -> None:
        rc = recover_cmd.main(
            [str(tmp_path / 'artifacts' / 'ghost'), '--root', str(tmp_path)],
        )
        assert rc == 2

    def test_cli_subprocess_happy_path(self, tmp_path: Path) -> None:
        """End-to-end ``python -m tools.runs.recover`` exits 0 and writes file."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.recover',
                str(run_dir),
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],  # repo root
        )
        assert result.returncode == 0, f'stderr={result.stderr!r}'
        assert (run_dir / 'metadata.toml').is_file()

    def test_cli_subprocess_then_list_shows_unknown(self, tmp_path: Path) -> None:
        """End-to-end: recover via subprocess → list via subprocess → row visible."""
        run_dir = _build_partial_dir(tmp_path, nnn='000099')
        repo_root_cwd = Path(__file__).resolve().parents[3]

        rec = subprocess.run(
            [sys.executable, '-m', 'tools.runs.recover', str(run_dir), '--root', str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=repo_root_cwd,
        )
        assert rec.returncode == 0

        lst = subprocess.run(
            [sys.executable, '-m', 'tools.runs.list', '--root', str(tmp_path), '--status', 'unknown'],
            capture_output=True,
            text=True,
            cwd=repo_root_cwd,
        )
        assert lst.returncode == 0
        assert '000099' in lst.stdout
        assert 'unknown' in lst.stdout

    def test_cli_subprocess_then_mark_killed(self, tmp_path: Path) -> None:
        """End-to-end: recover → mark killed → metadata.toml updated."""
        run_dir = _build_partial_dir(tmp_path, nnn='000088')
        repo_root_cwd = Path(__file__).resolve().parents[3]

        subprocess.run(
            [sys.executable, '-m', 'tools.runs.recover', str(run_dir), '--root', str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=repo_root_cwd,
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.mark',
                '88',
                '--status',
                'killed',
                '--notes',
                'manually recovered',
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=repo_root_cwd,
            check=True,
        )

        meta = schema.load_file(run_dir / 'metadata.toml')
        assert meta.status == 'killed'
        assert meta.notes == 'manually recovered'

    def test_cli_stderr_hint_includes_next_step(self, tmp_path: Path) -> None:
        """Operator-friendly hint nudges towards ``tools.runs.mark``."""
        run_dir = _build_partial_dir(tmp_path, nnn='000050')
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.recover',
                str(run_dir),
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        assert result.returncode == 0
        assert 'tools.runs.mark' in result.stderr
        assert '000050' in result.stderr


# --- Idempotence + re-recovery via rm ---------------------------------------


class TestIdempotence:
    def test_re_recovery_after_rm_succeeds(self, tmp_path: Path) -> None:
        """Once user rm's the synthesised metadata, recover can run again."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        recover_cmd.recover_metadata(tmp_path, run_dir)
        # Simulate "user wants to redo recovery".
        (run_dir / 'metadata.toml').unlink()
        # Second recover should succeed (no metadata to clobber).
        meta2 = recover_cmd.recover_metadata(tmp_path, run_dir)
        assert meta2.status == 'unknown'

    def test_recover_twice_back_to_back_raises(self, tmp_path: Path) -> None:
        """Second recover without rm raises FileExistsError (clobber-guard)."""
        run_dir = _build_partial_dir(tmp_path, nnn='000001')
        recover_cmd.recover_metadata(tmp_path, run_dir)
        with pytest.raises(FileExistsError):
            recover_cmd.recover_metadata(tmp_path, run_dir)
