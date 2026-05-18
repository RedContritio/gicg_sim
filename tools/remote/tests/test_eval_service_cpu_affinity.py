"""Tests for ``tools.remote.eval_service._apply_cpu_affinity`` parse + no-op paths.

The "actually pin" path (psutil.Process().cpu_affinity success) is
platform-dependent (Mac has no cpu_affinity) and is covered by the
Linux-only smoke at ``training/tests/test_mp_helpers_affinity.py``.
These tests focus on the parse + silent-skip contract that runs
identically on every platform.
"""

from __future__ import annotations

import pytest

from tools.remote.eval_service import _apply_cpu_affinity


def test_apply_cpu_affinity_none_is_noop():
    _apply_cpu_affinity(None)  # no raise


def test_apply_cpu_affinity_empty_string_is_noop():
    _apply_cpu_affinity('')  # no raise


def test_apply_cpu_affinity_bad_csv_raises_systemexit():
    with pytest.raises(SystemExit, match='parse error'):
        _apply_cpu_affinity('abc,def')
