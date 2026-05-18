"""Tests for ``LocalNetworkProvider`` ``use_jit_trace`` wiring.

Covers:
1. Default behavior (``use_jit_trace=False``) is unchanged: no trace
   attempted, forward routes through ``self.network`` directly.
2. ``use_jit_trace=True`` + traceable net: first forward triggers
   ``torch.jit.trace``; ``_traced_net`` populated; subsequent forwards
   reuse the traced module.
3. ``use_jit_trace=True`` + ``torch.jit.trace`` failure: provider logs
   one line, sets ``_trace_attempted=True``, leaves ``_traced_net=None``,
   and falls back to untraced forward without re-attempting trace on
   later calls.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.actor.network_provider import LocalNetworkProvider


class _SimpleNet(nn.Module):
    """Trivially traceable linear network."""

    def __init__(self, n_in: int = 4, n_out: int = 2) -> None:
        super().__init__()
        self.fc = nn.Linear(n_in, n_out)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_local_provider_default_no_trace():
    """Without ``use_jit_trace``, provider's trace state stays inert."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu')
    x = torch.randn(1, 4)
    out = prov.forward(x, None)
    assert out.shape == (1, 2)
    # No trace attempted, no traced module.
    assert prov._traced_net is None
    assert prov._trace_attempted is False
    assert prov._use_jit_trace is False


def test_local_provider_trace_succeeds_on_simple_network(monkeypatch):
    """Lazy first-forward trace populates ``_traced_net`` exactly once."""
    net = _SimpleNet()
    prov = LocalNetworkProvider(net, device='cpu', use_jit_trace=True)
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
    prov = LocalNetworkProvider(net, device='cpu', use_jit_trace=True)

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
    prov = LocalNetworkProvider(net, device='cpu', use_jit_trace=True)

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
