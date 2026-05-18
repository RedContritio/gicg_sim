"""End-to-end mp tests for InferenceServer use_jit_trace flag.

Tests black-box behavior across the multiprocessing.spawn boundary:
- Flag propagates from ctor to _server_loop without pickling errors
- Forward results are numerically correct regardless of trace path
- Weight-update lifecycle works (the trace-invalidation branch on the
  'weights' message executes without crash)

Trace closure state inside _server_loop is not directly observable from
the parent process — these tests cover the integration surface, not the
inner trace state machine (that is covered by test_jit_trace_provider.py
for the in-proc LocalNetworkProvider equivalent).
"""

from __future__ import annotations

import time

import torch
import torch.nn as nn

from training.core.actor.inference_client import InferenceClient
from training.core.actor.inference_server import InferenceServer


class _TinyNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc = nn.Linear(4, 3)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_use_jit_trace_flag_propagates_no_crash():
    """use_jit_trace=True pickles to spawn child + lazy first-batch
    trace path produces numerically correct output (trace success or
    fallback both acceptable — both must produce parity vs in-proc)."""
    torch.manual_seed(0)
    net = _TinyNet()
    server = InferenceServer(net, device='cpu', max_batch=2, batch_timeout_ms=5, use_jit_trace=True)
    client = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        # Fire 3 sequential requests; first triggers lazy trace (success
        # or fallback — both paths must produce correct output).
        for _ in range(3):
            x = torch.randn(1, 4)
            out = client.request(x, None)
            with torch.inference_mode():
                ref = net(x)
            assert torch.allclose(out, ref, atol=1e-6), 'output mismatch — trace or fallback corrupted forward'
    finally:
        client.close()
        server.stop()


def test_use_jit_trace_default_false_unchanged():
    """Sanity: adding use_jit_trace param didn't break default codepath."""
    torch.manual_seed(0)
    net = _TinyNet()
    server = InferenceServer(net, device='cpu', max_batch=2, batch_timeout_ms=5)  # default use_jit_trace
    client = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        x = torch.randn(1, 4)
        out = client.request(x, None)
        with torch.inference_mode():
            ref = net(x)
        assert torch.allclose(out, ref, atol=1e-6)
    finally:
        client.close()
        server.stop()


def test_use_jit_trace_weights_update_invalidates_without_crash():
    """End-to-end lifecycle with use_jit_trace=True survives a weights
    update; indirectly exercises _invalidate_trace in 'weights' handler.

    After zeroing all weights (Linear weight + bias), forward returns
    zeros — verifies the new state_dict actually propagated, not just
    that the server didn't crash."""
    torch.manual_seed(0)
    net = _TinyNet()
    server = InferenceServer(net, device='cpu', max_batch=2, batch_timeout_ms=5, use_jit_trace=True)
    client = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        x = torch.randn(1, 4)
        out_before = client.request(x, None)

        new_sd = {k: torch.zeros_like(v) for k, v in net.state_dict().items()}
        server.update_network(new_sd)

        # Poll until the weights update is observed (out diverges from out_before).
        # Bounded by 50 iterations × 20ms = 1s — generous for queue drain even
        # on a loaded CI runner.
        for _ in range(50):
            probe = client.request(x, None)
            if not torch.allclose(probe, out_before, atol=1e-6):
                break
            time.sleep(0.02)
        out_after = probe

        # Verify the output reflects the new (zeroed) weights, NOT the old.
        assert not torch.allclose(out_before, out_after, atol=1e-6), (
            'weights update did not propagate — server still serving old weights'
        )
        assert torch.allclose(out_after, torch.zeros(1, 3), atol=1e-6), (
            f'expected zero output after zeroing all weights, got {out_after}'
        )
    finally:
        client.close()
        server.stop()
