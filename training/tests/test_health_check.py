"""Unit tests for training.core.health_check.health_check.

Pure-function tests — no subprocess, no torch, no train_az loop.
Covers the v_loss warn + diverge branches with synthetic stats
dicts and rolling windows so that regressions in the thresholds
or the monotone detector don't slip through on a greenlit suite.
"""

from __future__ import annotations

from collections import deque

import pytest

from training.core.health_check import health_check


def _window(maxlen: int, values: list) -> deque:
    d: deque = deque(maxlen=maxlen)
    d.extend(values)
    return d


class TestHealthCheckNormal:
    def test_normal_loss_no_event(self):
        """Normal early-training v_loss (≈ 0.9) must not warn or raise
        even with a near-zero rolling median (the case that blew up
        the ratio-based version of the check)."""
        events = []
        window = _window(50, [0.0] * 40 + [0.5] * 10)

        def log(kind, data):
            events.append((kind, data))

        health_check({'value': 0.9}, window, log)
        assert events == []

    def test_flat_window_tolerated(self):
        """All-zero window (early training before any signal) with a
        typical 0.9 v_loss must not fire."""
        events = []
        window = _window(50, [0.0] * 50)
        health_check({'value': 0.9}, window, events.append)
        assert events == []


class TestHealthCheckWarn:
    def test_v_loss_above_warn_threshold_emits_warn(self):
        """v_loss > 5.0 triggers an informational ``health_warn`` but
        does NOT raise."""
        events = []
        window = _window(50, [1.0] * 50)

        def log(kind, data):
            events.append((kind, data))

        health_check({'value': 5.5}, window, log)
        assert len(events) == 1
        kind, data = events[0]
        assert kind == 'health_warn'
        assert data['value'] == 5.5
        assert data['metric'] == 'value_loss'


class TestHealthCheckDiverge:
    def test_monotone_divergence_raises(self):
        """v_loss > 7.0 AND a full window whose last 10 entries are
        monotonically non-decreasing → divergence, raise."""
        window = _window(50, [1.0] * 40 + [2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9])
        with pytest.raises(RuntimeError, match='diverged'):
            health_check({'value': 8.0}, window, lambda k, d: None)

    def test_non_monotone_above_diverge_only_warns(self):
        """v_loss > 7.0 but with a non-monotone last 10 → warn only,
        do not raise. This is the case where a single spike shows up
        mid-training but the trend isn't runaway growth."""
        events = []
        # Mix: up, down, up, down ... clearly not monotone
        tail = [2.0, 1.5, 2.5, 1.8, 2.6, 1.7, 2.7, 1.9, 2.8, 2.0]
        window = _window(50, [1.0] * 40 + tail)

        def log(kind, data):
            events.append((kind, data))

        health_check({'value': 8.0}, window, log)
        # warn only, no raise
        assert any(k == 'health_warn' for k, _ in events)
        assert all(k != 'diverged' for k, _ in events)

    def test_window_not_full_skips_diverge_even_at_raise_value(self):
        """Diverge path is gated on a FULL window so it can't fire
        in the first 50 steps. At step 30 even v_loss=8.0 only emits
        a warn."""
        events = []
        window = _window(50, [1.0] * 30)  # not full

        def log(kind, data):
            events.append((kind, data))

        health_check({'value': 8.0}, window, log)
        # only warn, never diverged
        assert all(k != 'diverged' for k, _ in events)
        assert any(k == 'health_warn' for k, _ in events)


class TestHealthCheckNaN:
    def test_non_finite_raises(self):
        with pytest.raises(RuntimeError, match='non-finite'):
            health_check(
                {'value': float('nan')},
                _window(50, []),
                lambda k, d: None,
            )

    def test_inf_raises(self):
        with pytest.raises(RuntimeError, match='non-finite'):
            health_check(
                {'value': float('inf')},
                _window(50, []),
                lambda k, d: None,
            )
