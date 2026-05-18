"""Sanity smoke for tools.dmc.profile_actor.

5-second subprocess invocation against the DMC smoke cfg. Goal: catch
tool-breakage regressions in CI without paying the 60s baseline cost
the human runs once for the notes.md hotspot table.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CFG_PATH = REPO_ROOT / 'configs' / 'dmc' / 'smoke.toml'


@pytest.mark.smoke
def test_profile_actor_runs_short_duration(tmp_path: Path) -> None:
    """5-second profile_actor run produces actor.prof + summary stdout."""
    prof_out = tmp_path / 'actor.prof'
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'tools.dmc.profile_actor',
            '--cfg',
            str(CFG_PATH),
            '--duration-seconds',
            '5',
            '--prof-output',
            str(prof_out),
            '--top-hotspots',
            '5',
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f'profile_actor exited {proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}'
    )
    assert prof_out.exists(), f'prof output {prof_out} not created'
    assert prof_out.stat().st_size > 0, f'prof output {prof_out} empty'
    assert 'per_actor_fps' in proc.stdout, f'summary missing per_actor_fps:\n{proc.stdout}'
    assert 'Top 5 hotspots' in proc.stdout, f'hotspot section missing:\n{proc.stdout}'
