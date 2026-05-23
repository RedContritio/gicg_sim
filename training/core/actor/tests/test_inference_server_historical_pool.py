"""D10 S1 — InferenceServer historical-net pool (infra-only, no wire).

Verifies:
  - slot=0 fast path bit-equal pre-D10 (cap=0 default disables pool)
  - push_historical_weights(slot=N, sd) ⇒ _get_network_by_slot(N) forwards
    same as a fresh net loaded with sd (in-proc white-box)
  - ring evict: len(non-zero) > historical_cap ⇒ oldest non-zero evicted
  - fail-loud契约: cap=0 调 push raise; slot 越界 raise; 未 push slot
    _get_network_by_slot raise KeyError (无 silent slot 0 fallback)
  - shared_cache 清: push 后实例侧 _networks 不与 slot 0 共用 underlying
    parameters (deepcopy semantics)
  - spawned proc smoke: push 走 queue 不抛, server 仍 alive, slot 0 forward 仍 work

Per spec, forward routing through socket is NOT yet wired (S5);
tests exercise the internal helper `_get_network_by_slot` directly.
"""

from __future__ import annotations

import pytest
import torch

from training.core.actor.inference_client import InferenceClient
from training.core.actor.inference_server import InferenceServer


class _TinyNet(torch.nn.Module):
    """Plain 2-layer net — picklable + deterministic forward for parity tests."""

    def __init__(self, seed: int = 0) -> None:
        super().__init__()
        g = torch.Generator().manual_seed(seed)
        self.fc1 = torch.nn.Linear(4, 8)
        self.fc2 = torch.nn.Linear(8, 3)
        # Replace init weights deterministically (seed-controlled).
        with torch.no_grad():
            for p in self.parameters():
                p.copy_(torch.randn(p.shape, generator=g))

    def forward(self, x, mask=None):
        return self.fc2(torch.relu(self.fc1(x)))


def _sd_clone(net: torch.nn.Module) -> dict:
    return {k: v.detach().clone() for k, v in net.state_dict().items()}


class TestHistoricalCapDisabledByDefault:
    """cap=0 (default) ⇒ pool disabled, push raises, slot 0 unchanged."""

    def test_default_cap_zero_push_raises(self):
        srv = InferenceServer(_TinyNet(seed=0), device='cpu')
        assert srv.historical_cap == 0
        with pytest.raises(ValueError, match='historical_cap=0'):
            srv.push_historical_weights(1, _sd_clone(_TinyNet(seed=1)))

    def test_slot_zero_get_returns_live_net(self):
        net = _TinyNet(seed=0)
        srv = InferenceServer(net, device='cpu')
        assert srv._get_network_by_slot(0) is srv.network

    def test_get_unknown_slot_raises_keyerror_not_fallback(self):
        srv = InferenceServer(_TinyNet(seed=0), device='cpu', historical_cap=2)
        with pytest.raises(KeyError, match='slot_id=1 not in pool'):
            srv._get_network_by_slot(1)


class TestPushHistoricalContract:
    """Slot-range fail-loud + bit-equal forward parity."""

    def test_slot_id_must_be_positive(self):
        srv = InferenceServer(_TinyNet(seed=0), device='cpu', historical_cap=2)
        with pytest.raises(ValueError, match='slot_id=0'):
            srv.push_historical_weights(0, _sd_clone(_TinyNet(seed=1)))
        with pytest.raises(ValueError, match='slot_id=-1'):
            srv.push_historical_weights(-1, _sd_clone(_TinyNet(seed=1)))

    def test_slot_id_above_cap_does_not_raise_but_evicts(self):
        """选 B 决议 — slot_id 是 caller-managed 单增 version_id,cap 是 ring
        容量。 push slot=3 with cap=2 不 raise,evict oldest slot 后 insert
        (FIFO 行为 详 TestRingEviction)。 此 test 仅 验 ≤ 1 边界 fail-loud。"""
        srv = InferenceServer(_TinyNet(seed=0), device='cpu', historical_cap=2)
        # 不该 raise — push slot=3 直接 add 后 (1 slot in pool),后续 evict 见 TestRingEviction
        srv.push_historical_weights(3, _sd_clone(_TinyNet(seed=1)))
        # 验 slot=3 实际 加入 pool
        assert srv._get_network_by_slot(3) is not None

    def test_push_then_forward_matches_fresh_net_with_sd(self):
        """White-box: _get_network_by_slot(N) forward bit-equal to a fresh
        net.load_state_dict(sd). Verifies sd is faithfully materialized."""
        live = _TinyNet(seed=0)
        srv = InferenceServer(live, device='cpu', historical_cap=2)
        snap_net = _TinyNet(seed=42)
        sd = _sd_clone(snap_net)

        srv.push_historical_weights(1, sd)

        x = torch.randn(2, 4)
        with torch.inference_mode():
            pool_out = srv._get_network_by_slot(1)(x)
            ref_out = snap_net(x)
        assert torch.equal(pool_out, ref_out), (
            f'historical slot 1 diverged from fresh-loaded reference; max diff '
            f'{(pool_out - ref_out).abs().max()}'
        )

    def test_slot_zero_fast_path_bit_equal_after_push(self):
        """slot 0 forward must be unaffected by historical pushes."""
        live = _TinyNet(seed=0)
        srv = InferenceServer(live, device='cpu', historical_cap=2)
        x = torch.randn(2, 4)
        with torch.inference_mode():
            before = srv.forward_one(x, None)
        srv.push_historical_weights(1, _sd_clone(_TinyNet(seed=99)))
        with torch.inference_mode():
            after = srv.forward_one(x, None)
        assert torch.equal(before, after), 'slot 0 fast path drifted after historical push'

    def test_historical_net_isolated_from_live(self):
        """Push slot 1, mutate live net params, slot 1 net must NOT track
        (deepcopy semantics, not view sharing)."""
        live = _TinyNet(seed=0)
        srv = InferenceServer(live, device='cpu', historical_cap=2)
        sd = _sd_clone(_TinyNet(seed=42))
        srv.push_historical_weights(1, sd)
        hist_net = srv._get_network_by_slot(1)

        # Mutate live in place.
        with torch.no_grad():
            for p in live.parameters():
                p.zero_()

        # Historical slot 1 must still reflect the original sd.
        x = torch.randn(2, 4)
        with torch.inference_mode():
            pool_out = hist_net(x)
            ref_out = _TinyNet(seed=42).forward(x)
        # Re-init seed=42 same construction ⇒ same params ⇒ same forward
        # (sd was cloned from that net). Bit-equal.
        assert torch.equal(pool_out, ref_out), 'historical slot mutated by live-net update'


class TestRingEviction:
    """FIFO evict oldest non-zero slot when count > cap."""

    def test_evict_oldest_when_exceeding_cap(self):
        srv = InferenceServer(_TinyNet(seed=0), device='cpu', historical_cap=2)
        sd1 = _sd_clone(_TinyNet(seed=1))
        sd2 = _sd_clone(_TinyNet(seed=2))
        sd3 = _sd_clone(_TinyNet(seed=3))

        srv.push_historical_weights(1, sd1)
        srv.push_historical_weights(2, sd2)
        # cap=2 reached. Push slot 3 ⇒ evict slot 1 (FIFO oldest).
        srv.push_historical_weights(3, sd3)

        assert sorted(srv._networks.keys()) == [0, 2, 3]
        with pytest.raises(KeyError):
            srv._get_network_by_slot(1)

    def test_re_push_same_slot_refreshes_fifo_order(self):
        """Re-pushing an existing slot moves it to the FIFO tail (treated
        as fresh insertion), not duplicates it."""
        srv = InferenceServer(_TinyNet(seed=0), device='cpu', historical_cap=2)
        sd_a = _sd_clone(_TinyNet(seed=1))
        sd_b = _sd_clone(_TinyNet(seed=2))
        sd_a_refresh = _sd_clone(_TinyNet(seed=11))

        srv.push_historical_weights(1, sd_a)
        srv.push_historical_weights(2, sd_b)
        srv.push_historical_weights(1, sd_a_refresh)  # refresh slot 1 → tail
        srv.push_historical_weights(3, _sd_clone(_TinyNet(seed=3)))
        # Now FIFO is [2, 1, 3] post-refresh; cap=2 ⇒ evict 2 (oldest).
        assert sorted(srv._networks.keys()) == [0, 1, 3]

        # slot 1 must reflect REFRESHED sd, not original sd_a.
        x = torch.randn(2, 4)
        with torch.inference_mode():
            pool_out = srv._get_network_by_slot(1)(x)
            ref_out = _TinyNet(seed=11)(x)
        assert torch.equal(pool_out, ref_out)


class TestSpawnedSmoke:
    """Light smoke — push via queue does not kill server; slot 0 still serves."""

    def test_push_historical_via_spawn_keeps_server_alive(self):
        net = _TinyNet(seed=0)
        srv = InferenceServer(
            net, device='cpu', max_batch=2, batch_timeout_ms=10, historical_cap=2
        )
        client = InferenceClient.attach_to_server(srv, timeout_ms=15000)
        srv.start(wait_ready_s=15.0)
        try:
            # baseline slot-0 forward works.
            x = torch.randn(1, 4)
            r1 = client.request(x, None)
            with torch.inference_mode():
                ref = net(x)
            assert torch.allclose(r1, ref, atol=1e-6)

            # Push a historical snapshot — message must traverse spawn,
            # be handled by _handle_weights_versioned, server stays alive.
            srv.push_historical_weights(1, _sd_clone(_TinyNet(seed=42)))

            # slot 0 fast path still works post-push.
            r2 = client.request(x, None)
            assert torch.allclose(r2, ref, atol=1e-6), 'slot 0 forward broke after historical push'

            # Server proc still alive.
            assert srv.is_running()
        finally:
            client.close()
            srv.stop()
