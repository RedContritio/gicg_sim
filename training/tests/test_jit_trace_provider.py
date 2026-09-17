"""Tests for ``LocalNetworkProvider`` inference_acceleration wiring.

Covers:
1. Default behavior (``inference_acceleration='none'``) is unchanged:
   no trace attempted, forward routes through ``self.network`` directly.
2. ``inference_acceleration='trace'`` + traceable net: first forward
   triggers ``torch.jit.trace``; ``_traced_net`` populated; subsequent
   forwards reuse the traced module.
3. ``inference_acceleration='trace'`` + ``torch.jit.trace`` failure:
   provider logs one line, sets ``_trace_attempted=True``, leaves
   ``_traced_net=None``, and falls back to untraced forward without
   re-attempting trace on later calls.
4. ``inference_acceleration='compile'``: torch.compile invoked once at
   ctor; forward produces correct output; failure → graceful fallback.
5. Invalid ``inference_acceleration`` value raises.
6. ``use_jit_trace=True`` back-compat alias emits DeprecationWarning
   and sets ``_mode='trace'``.
"""

from __future__ import annotations

import warnings

import pytest
import torch
import torch.nn as nn

from training.core.actor.network_provider import LocalNetworkProvider
from training.paradigms.ppo.mp_factories import _PPOActorProvider


class _SimpleNet(nn.Module):
    """Trivially traceable linear network."""

    def __init__(self, n_in: int = 4, n_out: int = 2) -> None:
        super().__init__()
        self.fc = nn.Linear(n_in, n_out)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_local_provider_default_no_trace():
    """Default ``inference_acceleration='none'`` keeps trace state inert."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu')
    x = torch.randn(1, 4)
    out = prov.forward(x, None)
    assert out.shape == (1, 2)
    # No trace attempted, no traced module.
    assert prov._traced_net is None
    assert prov._trace_attempted is False
    assert prov._use_jit_trace is False
    assert prov._mode == 'none'


def test_local_provider_trace_succeeds_on_simple_network(monkeypatch):
    """Lazy first-forward trace populates ``_traced_net`` exactly once."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='trace')
    assert prov._traced_net is None
    assert prov._trace_attempted is False

    # Count ``torch.jit.trace`` invocations so we can confirm the
    # second forward does NOT re-trace.
    call_count = {'n': 0}
    real_trace = torch.jit.trace

    def _counting_trace(*args, **kwargs):
        call_count['n'] += 1
        return real_trace(*args, **kwargs)

    monkeypatch.setattr(torch.jit, 'trace', _counting_trace)

    x = torch.randn(1, 4)
    out1 = prov.forward(x, None)
    assert out1.shape == (1, 2)
    assert prov._trace_attempted is True
    assert prov._traced_net is not None
    assert call_count['n'] == 1

    # Second forward reuses traced module — no additional trace call.
    out2 = prov.forward(x, None)
    assert out2.shape == (1, 2)
    assert call_count['n'] == 1

    # Numeric agreement between traced + untraced (same weights).
    with torch.inference_mode():
        ref = net(x)
    assert torch.allclose(out1, ref, atol=1e-5)
    assert torch.allclose(out2, ref, atol=1e-5)


def test_local_provider_trace_fallback_on_failure(monkeypatch):
    """Trace exception → log + permanent fallback, no per-call retry."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='trace')

    # Force ``torch.jit.trace`` to raise on the first attempt.
    call_count = {'n': 0}

    def _raising_trace(*args, **kwargs):
        call_count['n'] += 1
        raise RuntimeError('synthetic trace failure for test')

    monkeypatch.setattr(torch.jit, 'trace', _raising_trace)

    x = torch.randn(1, 4)
    out1 = prov.forward(x, None)
    # First forward still returns correct shape via untraced fallback.
    assert out1.shape == (1, 2)
    assert prov._trace_attempted is True
    assert prov._traced_net is None
    assert call_count['n'] == 1

    # Subsequent forwards do NOT retry trace.
    out2 = prov.forward(x, None)
    assert out2.shape == (1, 2)
    assert call_count['n'] == 1

    # Output matches untraced reference (we never traced).
    with torch.inference_mode():
        ref = net(x)
    assert torch.allclose(out1, ref, atol=1e-5)
    assert torch.allclose(out2, ref, atol=1e-5)


def test_local_provider_update_weights_invalidates_traced_module(monkeypatch):
    """``update_weights`` resets trace state so the next forward re-traces."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='trace')

    call_count = {'n': 0}
    real_trace = torch.jit.trace

    def _counting_trace(*args, **kwargs):
        call_count['n'] += 1
        return real_trace(*args, **kwargs)

    monkeypatch.setattr(torch.jit, 'trace', _counting_trace)

    x = torch.randn(1, 4)
    prov.forward(x, None)
    assert call_count['n'] == 1
    assert prov._traced_net is not None

    # Load fresh weights — should invalidate traced module.
    new_net = _SimpleNet()
    prov.update_weights(state_dict=new_net.state_dict())
    assert prov._traced_net is None
    assert prov._trace_attempted is False

    # Next forward re-traces.
    prov.forward(x, None)
    assert call_count['n'] == 2
    assert prov._traced_net is not None


def test_local_provider_shm_update_invalidates_traced_module(monkeypatch):
    """SHM polling follows the same trace invalidation path as direct loads."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='trace')

    call_count = {'n': 0}
    real_trace = torch.jit.trace

    def _counting_trace(*args, **kwargs):
        call_count['n'] += 1
        return real_trace(*args, **kwargs)

    monkeypatch.setattr(torch.jit, 'trace', _counting_trace)

    x = torch.randn(1, 4)
    prov.forward(x, None)
    assert call_count['n'] == 1

    class _SHM:
        def read(self, tag):
            return _SimpleNet().state_dict(), 9

    prov._shm = _SHM()
    assert prov.update_weights() == 9
    assert prov._traced_net is None
    assert prov._trace_attempted is False

    prov.forward(x, None)
    assert call_count['n'] == 2


def test_ppo_provider_shm_update_invalidates_traced_module(monkeypatch):
    net = _SimpleNet()
    local = LocalNetworkProvider(net, device='cpu', inference_acceleration='trace')
    call_count = {'n': 0}
    real_trace = torch.jit.trace

    def _counting_trace(*args, **kwargs):
        call_count['n'] += 1
        return real_trace(*args, **kwargs)

    monkeypatch.setattr(torch.jit, 'trace', _counting_trace)

    class _SHM:
        def read(self, tag):
            return _SimpleNet().state_dict(), 11

    prov = _PPOActorProvider(local, _SHM())
    x = torch.randn(1, 4)
    prov.forward(x, None)
    assert call_count['n'] == 1
    assert prov.update_weights() == 11
    assert local._traced_net is None
    assert local._trace_attempted is False
    prov.forward(x, None)
    assert call_count['n'] == 2


# ---------- inference_acceleration='compile' tests ---------- #


def test_local_provider_compile_mode_basic():
    """``inference_acceleration='compile'`` produces output matching the
    raw network on a trivially compilable Linear net. If torch.compile
    cannot construct the wrapper on this platform we fall back to raw —
    still correct."""
    torch.manual_seed(0)
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='compile')
    assert prov._mode == 'compile'

    x = torch.randn(2, 4)
    out = prov.forward(x, None)
    assert out.shape == (2, 2)

    with torch.inference_mode():
        ref = net(x)
    # torch.compile may fall back gracefully (compiled_net is None) on
    # platforms where the backend init failed; numerics still must match.
    assert torch.allclose(out, ref, atol=1e-5), f'compile-mode output diverged from raw forward: {out} vs {ref}'


def test_local_provider_compile_mode_falls_back_on_failure(monkeypatch):
    """torch.compile raising at ctor → ``_compiled_net is None`` and
    forward routes through raw network without crash."""
    net = _SimpleNet()

    def _raising_compile(*args, **kwargs):
        raise RuntimeError('synthetic torch.compile failure for test')

    monkeypatch.setattr(torch, 'compile', _raising_compile)

    prov = LocalNetworkProvider(net, device='cpu', inference_acceleration='compile')
    assert prov._mode == 'compile'
    assert prov._compiled_net is None

    x = torch.randn(1, 4)
    out = prov.forward(x, None)
    assert out.shape == (1, 2)
    with torch.inference_mode():
        ref = net(x)
    assert torch.allclose(out, ref, atol=1e-5)


def test_local_provider_invalid_acceleration_raises():
    """Unknown ``inference_acceleration`` value raises ValueError."""
    net = _SimpleNet()
    with pytest.raises(ValueError, match='inference_acceleration must be one of'):
        LocalNetworkProvider(net, device='cpu', inference_acceleration='bogus')


def test_local_provider_use_jit_trace_back_compat_warning():
    """Legacy ``use_jit_trace=True`` still works but emits
    DeprecationWarning and converts internally to ``'trace'`` mode."""
    net = _SimpleNet()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        prov = LocalNetworkProvider(net, device='cpu', use_jit_trace=True)
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 1, f'expected 1 DeprecationWarning, got {len(dep_warnings)}'
    assert 'use_jit_trace' in str(dep_warnings[0].message)
    assert prov._mode == 'trace'
    assert prov._use_jit_trace is True  # back-compat property reflects mode

    # Forward still works (and triggers lazy trace).
    x = torch.randn(1, 4)
    out = prov.forward(x, None)
    assert out.shape == (1, 2)
    assert prov._trace_attempted is True
