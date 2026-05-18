"""Tests for ``harden_child_env(affinity=...)`` — T-3.4.5b verification.

Three cases:

1. default (no affinity arg) — function still works the way every existing
   caller invokes it.
2. affinity provided on a platform that supports ``cpu_affinity`` — verify
   the pin actually took effect by reading the affinity back.
3. affinity provided on a platform that lacks ``cpu_affinity`` (Mac) — the
   call must not raise, per the silent-skip contract.

We use the real ``psutil`` (no mocks) since the whole point is verifying
real platform behavior, and the silent-skip path is exactly the surprise
we want to test against future regressions.
"""

from __future__ import annotations

import psutil
import pytest

from training.core.actor._mp_helpers import harden_child_env


_HAS_CPU_AFFINITY = hasattr(psutil.Process(), 'cpu_affinity')


def test_harden_child_env_no_affinity_default() -> None:
    """Existing callers (actor_process.py, inference_server.py) invoke
    with no args — must remain a no-raise no-op."""
    harden_child_env()  # idempotent; no exception is the success criterion


@pytest.mark.skipif(not _HAS_CPU_AFFINITY, reason='platform without cpu_affinity (macOS)')
def test_harden_child_env_with_affinity_applied_on_supported_platform() -> None:
    """On Linux/Windows, ``harden_child_env(affinity=[cpu])`` must pin
    the current process to exactly that CPU set."""
    proc = psutil.Process()
    original = proc.cpu_affinity()
    try:
        # Pick the lowest available logical CPU — guaranteed present.
        target_cpu = sorted(original)[0]
        harden_child_env(affinity=[target_cpu])
        got = proc.cpu_affinity()
        assert got == [target_cpu], f'expected pin to [{target_cpu}], got {got}'
    finally:
        # Restore the original mask so the test process doesn't stay pinned
        # and starve subsequent tests / pytest-xdist workers.
        proc.cpu_affinity(original)


@pytest.mark.skipif(_HAS_CPU_AFFINITY, reason='not Mac — cpu_affinity is supported here')
def test_harden_child_env_with_affinity_skipped_on_mac_silently() -> None:
    """On Mac (no ``cpu_affinity``), passing an affinity list must
    silently no-op rather than raising AttributeError.

    The whole point of the silent-skip is that DMC cfgs can specify a
    Windows X3D core layout and still load on Mac dev boxes for smoke /
    pipeline tests."""
    harden_child_env(affinity=[0])  # no exception is the success criterion
