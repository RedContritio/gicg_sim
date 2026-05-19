"""Tests for training/buffer.py — replay buffer semantics."""

from __future__ import annotations

import random

import numpy as np
import pytest

from training.paradigms.az.buffer import (
    GAME_STATIC_KEYS,
    STEP_DYNAMIC_KEYS,
    ReplayBuffer,
)


# Round-6 S-3: 共享 typed obs padding helper (替原 Round-5 inline)
from training.tests._typed_obs_fixtures import (  # noqa: E402
    make_modifier_log_padding_np as _make_modifier_log_padding,
    make_recent_damage_padding_np as _make_recent_damage_padding,
)


def _fake_static(n_slots=128, n_hooks=8, d_model=16, max_ops=12, fields_per_op=5):
    # d_model kept as parameter for API compat but no longer stored in
    # static — IR ops are stored, hook_emb is re-encoded in forward_batch.
    del d_model
    return {
        'hook_ir': np.random.randint(1, 14, (n_hooks, max_ops, fields_per_op), dtype=np.int64),
        'hook_mask': np.ones(n_hooks, dtype=bool),
        'counter_sids': np.arange(n_slots, dtype=np.int64),
        'active_slot_mask': np.ones(n_slots, dtype=bool),
        'char_skill_refs': -np.ones((2, 6, 10), dtype=np.int64),
    }


def _fake_step(
    *,
    n_slots=128,
    max_actions=6,
    n_legal=3,
    z=0.0,
    is_discovery=False,
    pi_nonzero_spread_over=None,
):
    """One plausible per-step dict. pi_target is uniform over the
    first `n_legal` slots by default; pass `pi_nonzero_spread_over`
    to force non-zero slots only at specified indices."""
    pi = np.zeros(max_actions, dtype=np.float32)
    if pi_nonzero_spread_over is None:
        pi[:n_legal] = 1.0 / n_legal
    else:
        for idx in pi_nonzero_spread_over:
            pi[idx] = 1.0 / len(pi_nonzero_spread_over)

    legal = np.zeros(max_actions, dtype=bool)
    legal[:n_legal] = True

    return {
        'counter_values': np.random.randn(n_slots).astype(np.float32),
        'counter_target': np.random.randn(n_slots).astype(np.float32),
        'has_counter_target': True,
        'meta': np.array([3.0, 1.0, 1.0], dtype=np.float32),
        'card_buckets': np.zeros((4, 80), dtype=np.float32),
        'enemy_sizes': np.zeros(2, dtype=np.float32),
        # ADR-0019 §B.2/§B.3c typed obs segments — Round-5 S2 sentinel:
        # categorical=-2,scalar=0 (matching engine encode_*_padding);
        # prepare_skill=-1 ("no prepare" real, encodePrepareSkill convention)
        'recent_damage': _make_recent_damage_padding(),
        'prepare_skill': np.full((2, 2), -1.0, dtype=np.float32),
        'modifier_log': _make_modifier_log_padding(),
        'action_refs': np.full((max_actions, 3), -1, dtype=np.int64),
        'action_payments': np.zeros((max_actions, 8), dtype=np.float32),
        'legal_mask': legal,
        'pi_target': pi,
        'z_target': float(z),
        'is_discovery': is_discovery,
    }


class TestBufferAddSample:
    def test_add_then_sample_roundtrip(self):
        rb = ReplayBuffer(capacity=100)
        static = _fake_static()
        steps = [_fake_step(z=1.0) for _ in range(5)]
        gid = rb.add_trajectory(static, steps)
        assert isinstance(gid, int)
        assert len(rb) == 5
        assert rb.n_games() == 1

        rng = random.Random(42)
        batch = rb.sample(batch_size=3, rng=rng)
        assert batch['counter_values'].shape == (3, 128)
        assert batch['hook_ir'].shape == (3, 8, 12, 5)
        assert batch['hook_mask'].shape == (3, 8)
        assert batch['counter_sids'].shape == (3, 128)
        assert batch['card_buckets'].shape == (3, 4, 80)
        assert batch['enemy_sizes'].shape == (3, 2)
        assert batch['meta'].shape == (3, 3)
        assert batch['action_refs'].shape == (3, 6, 3)
        assert batch['action_payments'].shape == (3, 6, 8)
        assert batch['legal_mask'].shape == (3, 6)
        assert batch['pi_target'].shape == (3, 6)
        assert batch['z_target'].shape == (3,)
        # All z were 1.0
        assert (batch['z_target'] == 1.0).all()

    def test_sample_smaller_than_request(self):
        """Buffer holds 4 entries; asking for 10 returns exactly 4."""
        rb = ReplayBuffer(capacity=100)
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(4)])
        rng = random.Random(0)
        batch = rb.sample(batch_size=10, rng=rng)
        assert batch['counter_values'].shape[0] == 4

    def test_empty_sample_raises(self):
        rb = ReplayBuffer(capacity=100)
        rng = random.Random(0)
        with pytest.raises(RuntimeError, match='empty'):
            rb.sample(batch_size=1, rng=rng)


class TestBufferRing:
    def test_ring_wrap_evicts_oldest(self):
        rb = ReplayBuffer(capacity=10)
        # Add 3 games of 5 steps each = 15 steps > capacity=10
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        assert len(rb) == 10

    def test_evicted_game_static_is_freed(self):
        """After a full ring wrap past game 0, game 0's static cache
        must be released (refcount hit zero)."""
        rb = ReplayBuffer(capacity=5)
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        assert rb.n_games() == 1
        # Add 5 more → completely displaces game 0
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        assert rb.n_games() == 1  # only game 1 remains
        assert len(rb) == 5

    def test_partial_eviction_keeps_static(self):
        rb = ReplayBuffer(capacity=10)
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(8)])
        assert rb.n_games() == 1
        rb.add_trajectory(_fake_static(), [_fake_step() for _ in range(5)])
        # 3 steps from game 0 still in ring, so static[0] survives.
        assert rb.n_games() == 2
        assert len(rb) == 10


class TestBufferPriority:
    def test_discovery_oversampled(self):
        """1 discovery step among 99 normal steps: with
        priority_weight=3.0 the expected selection share is
        3 / (3 + 99) ≈ 2.94%. Over 10000 draws the discovery step
        should be picked well above its uniform share of 1%."""
        rb = ReplayBuffer(capacity=200, priority_weight=3.0)
        steps = [_fake_step(is_discovery=False) for _ in range(99)]
        steps.append(_fake_step(is_discovery=True))
        rb.add_trajectory(_fake_static(), steps)

        rng = random.Random(1234)
        hits_discovery = 0
        N_DRAWS = 10000
        BATCH = 1
        for _ in range(N_DRAWS):
            batch = rb.sample(BATCH, rng)
            # pi_target comes from the step dict. We encoded no special
            # marker for discovery in the per-step data — use the fact
            # that the discovery step is the ONLY one whose
            # meta[0]==3 etc. is indistinguishable. Trick: mark it via
            # z_target instead. Redo:
            # (actually this test builds its own marker — see below.)
            pass
        # The lazy "pass" above means we need a marker. Rewrite using
        # z_target as the discovery marker (no side-effect on the
        # test's correctness — z is just a float field we control).
        rb2 = ReplayBuffer(capacity=200, priority_weight=3.0)
        normal = [_fake_step(is_discovery=False, z=0.0) for _ in range(99)]
        disc = _fake_step(is_discovery=True, z=99.0)
        rb2.add_trajectory(_fake_static(), normal + [disc])

        rng = random.Random(1234)
        hits = 0
        for _ in range(N_DRAWS):
            batch = rb2.sample(BATCH, rng)
            if float(batch['z_target'][0]) == 99.0:
                hits += 1
        share = hits / N_DRAWS
        # Uniform share = 1% = 0.01
        # Priority share = 3/102 ≈ 0.0294
        assert 0.02 < share < 0.05, (
            f'discovery share {share:.4f} outside expected range [0.02, 0.05] for priority_weight=3.0'
        )

    def test_priority_weight_1_is_uniform(self):
        """priority_weight=1.0 disables the weighting — discovery
        steps are sampled at their naive frequency."""
        rb = ReplayBuffer(capacity=200, priority_weight=1.0)
        normal = [_fake_step(is_discovery=False, z=0.0) for _ in range(99)]
        disc = _fake_step(is_discovery=True, z=99.0)
        rb.add_trajectory(_fake_static(), normal + [disc])

        rng = random.Random(42)
        hits = 0
        N = 5000
        for _ in range(N):
            b = rb.sample(1, rng)
            if float(b['z_target'][0]) == 99.0:
                hits += 1
        share = hits / N
        assert 0.005 < share < 0.02, f'uniform share {share:.4f} outside [0.005, 0.02]'


class TestBufferValidation:
    def test_missing_static_key_raises(self):
        rb = ReplayBuffer(capacity=10)
        bad = _fake_static()
        del bad['hook_mask']
        with pytest.raises(KeyError, match='hook_mask'):
            rb.add_trajectory(bad, [_fake_step()])

    def test_missing_step_key_raises(self):
        rb = ReplayBuffer(capacity=10)
        bad = _fake_step()
        del bad['z_target']
        with pytest.raises(KeyError, match='z_target'):
            rb.add_trajectory(_fake_static(), [bad])

    def test_empty_trajectory_raises(self):
        rb = ReplayBuffer(capacity=10)
        with pytest.raises(ValueError, match='empty'):
            rb.add_trajectory(_fake_static(), [])

    def test_bad_capacity_raises(self):
        with pytest.raises(ValueError, match='positive'):
            ReplayBuffer(capacity=0)

    def test_priority_weight_below_one_raises(self):
        with pytest.raises(ValueError, match='priority_weight'):
            ReplayBuffer(capacity=10, priority_weight=0.5)


def test_full_key_coverage():
    """Sanity: our sentinel KEY constants match what _fake_step actually
    produces. If someone adds a new required field, the test will fail
    here first instead of in a downstream obscure pytest error."""
    assert set(STEP_DYNAMIC_KEYS) == set(_fake_step().keys())
    assert set(GAME_STATIC_KEYS) == set(_fake_static().keys())
