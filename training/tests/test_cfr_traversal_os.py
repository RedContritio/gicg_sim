"""Tests for training/paradigms/cfr/legacy/traversal."""

from __future__ import annotations

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.cfr import AdvantageNet, CFRNetConfig
from training.paradigms.cfr.reservoir import (
    AdvantageBuffer,
    StrategyBuffer,
    ValueBuffer,
)
from training.paradigms.cfr.traversal import CFRTraverser, TraversalConfig
from training.core.step_encoding import pad_action_payments, pad_action_refs

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


# Network / buffer shape constants for the smoke game. These MUST match
# the engine's capacity (set at engine build time: 900 hooks, 120 tokens
# per hook) — the static obs layout encodes that size exactly.
D_MODEL = 8
MAX_TOK = 64
N_HOOKS_CAP = 900
MAX_ACTIONS = 2048
BUFFER_CAP = 2048


# --------------------------------------------------------------------------- #
# Padding helpers (pure unit tests)


class TestPadActionRefs:
    def test_pad_to_max(self):
        refs = np.array([[0, 1, 2], [1, 3, 4]], dtype=np.int32)
        padded = pad_action_refs(refs, max_actions=5)
        assert padded.shape == (5, 3)
        # First two rows preserved
        np.testing.assert_array_equal(padded[:2], refs)
        # Padding slots use END_TURN + -1 refs
        from training.core.obs_constants import ACTION_END_TURN

        assert (padded[2:, 0] == ACTION_END_TURN).all()
        assert (padded[2:, 1] == -1).all()

    def test_pad_exact_fit(self):
        refs = np.array([[0, 1, 2]], dtype=np.int32)
        padded = pad_action_refs(refs, max_actions=1)
        np.testing.assert_array_equal(padded, refs.astype(np.int64))

    def test_pad_empty(self):
        refs = np.zeros((0, 3), dtype=np.int32)
        padded = pad_action_refs(refs, max_actions=3)
        assert padded.shape == (3, 3)


class TestPadActionPayments:
    def test_pad_to_max(self):
        pay = np.array([[1, 0, 0, 0, 0, 0, 0, 0]], dtype=np.float32)
        padded = pad_action_payments(pay, max_actions=3)
        assert padded.shape == (3, 8)
        np.testing.assert_array_equal(padded[0], pay[0])
        assert (padded[1:] == 0).all()


# --------------------------------------------------------------------------- #
# Regret estimate sign check (pure unit test)


class TestRegretEstimate:
    def _tvr(self):
        cfg = CFRNetConfig(
            n_counter_slots=16,
            n_hooks=16,
            max_ops_per_hook=4,
            max_actions=4,
            d_model=D_MODEL,
            n_cross_layers=1,
            dropout=0.0,
        )
        net = AdvantageNet(cfg)
        return CFRTraverser(
            advantage_nets=[net, AdvantageNet(cfg)],
            n_counter_slots=16,
            max_ops_per_hook=4,
            n_hooks_capacity=16,
            max_actions=4,
            advantage_buffers=[
                AdvantageBuffer(capacity=16, max_actions=4),
                AdvantageBuffer(capacity=16, max_actions=4),
            ],
            strategy_buffer=StrategyBuffer(capacity=16, max_actions=4),
            value_buffer=ValueBuffer(capacity=16),
            rng=random.Random(0),
        )

    def test_sampled_action_gets_positive_regret_on_win(self):
        t = self._tvr()
        policy = np.array([0.1, 0.3, 0.6, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, True, False])
        # Correct form (Lanctot 2013 Def.4):
        #   r[sampled] = W·z·(1 − σ(a*))/q(a*)
        #   r[non-sampled legal] = -W·z·σ(a*)/q(a*)   (σ of SAMPLED, not of a)
        #   r[illegal] = 0
        # sampled=2, σ(a*)=0.6, q=0.6, z=1, W=1:
        #   r[2] = (1-0.6)/0.6 = 0.667
        #   r[0] = r[1] = -0.6/0.6 = -1.0
        regret = t._regret_estimate(
            policy,
            sampled_action=2,
            q_sampled=0.6,
            z=1.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        assert regret[2] == pytest.approx((1.0 - 0.6) / 0.6, abs=1e-5)
        assert regret[0] == pytest.approx(-0.6 / 0.6, abs=1e-5)
        assert regret[1] == pytest.approx(-0.6 / 0.6, abs=1e-5)
        assert regret[3] == pytest.approx(0.0, abs=1e-5)

    def test_sampled_action_gets_negative_regret_on_loss(self):
        t = self._tvr()
        policy = np.array([0.1, 0.3, 0.6, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, True, False])
        # On loss (z = -1): sampled action gets negative regret; non-
        # sampled legal actions get positive (counterfactual "should
        # have taken this instead"). Illegal slots stay at 0.
        regret = t._regret_estimate(
            policy,
            sampled_action=2,
            q_sampled=0.6,
            z=-1.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        assert regret[2] < 0.0
        assert regret[0] > 0.0
        assert regret[1] > 0.0
        # Non-sampled legal actions get the SAME value (Def.4: all -σ(a*)/q).
        assert regret[0] == pytest.approx(regret[1], abs=1e-6)
        assert regret[3] == pytest.approx(0.0, abs=1e-6)

    def test_draw_gives_zero_regret(self):
        t = self._tvr()
        policy = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, False, False])
        regret = t._regret_estimate(
            policy,
            sampled_action=0,
            q_sampled=0.5,
            z=0.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        np.testing.assert_array_equal(regret, np.zeros(4, dtype=np.float32))

    def test_weight_scales_linearly(self):
        t = self._tvr()
        policy = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, False, False])
        r1 = t._regret_estimate(
            policy,
            sampled_action=0,
            q_sampled=0.5,
            z=1.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        r2 = t._regret_estimate(
            policy,
            sampled_action=0,
            q_sampled=0.5,
            z=1.0,
            weight=3.0,
            legal_mask=legal_mask,
        )
        np.testing.assert_allclose(r2, 3.0 * r1, atol=1e-5)

    def test_q_floor_prevents_explosion(self):
        """When q_sampled is zero (degenerate sampling), the 1/q term
        must be clamped to keep regret finite."""
        t = self._tvr()
        policy = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, False, False])
        regret = t._regret_estimate(
            policy,
            sampled_action=0,
            q_sampled=0.0,
            z=1.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        assert np.all(np.isfinite(regret))
        # floor at 1e-6, so 1/q is at most 1e6
        assert abs(regret[0]) < 2e6

    def test_illegal_slots_zero(self):
        """Illegal action slots must receive 0 regret regardless of
        σ or z — the advantage net shouldn't be trained on their
        values. With the Def.4 formula, non-sampled legal actions all
        get -W·z·σ(a*)/q(a*), so without explicit masking illegal
        slots would inherit that non-zero factor."""
        t = self._tvr()
        policy = np.array([0.7, 0.3, 0.0, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, False, False])
        regret = t._regret_estimate(
            policy,
            sampled_action=0,
            q_sampled=0.7,
            z=1.0,
            weight=1.0,
            legal_mask=legal_mask,
        )
        assert regret[2] == 0.0
        assert regret[3] == 0.0


class TestSamplingDist:
    def _tvr(self, eps: float):
        cfg = CFRNetConfig(
            n_counter_slots=16,
            n_hooks=16,
            max_ops_per_hook=4,
            max_actions=4,
            d_model=D_MODEL,
            n_cross_layers=1,
            dropout=0.0,
        )
        net = AdvantageNet(cfg)
        return CFRTraverser(
            advantage_nets=[net, AdvantageNet(cfg)],
            n_counter_slots=16,
            max_ops_per_hook=4,
            n_hooks_capacity=16,
            max_actions=4,
            advantage_buffers=[
                AdvantageBuffer(capacity=16, max_actions=4),
                AdvantageBuffer(capacity=16, max_actions=4),
            ],
            strategy_buffer=StrategyBuffer(capacity=16, max_actions=4),
            value_buffer=ValueBuffer(capacity=16),
            config=TraversalConfig(epsilon=eps),
            rng=random.Random(0),
        )

    def test_epsilon_zero_equals_policy(self):
        t = self._tvr(eps=0.0)
        policy = np.array([0.1, 0.3, 0.6, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, True, False])
        q = t._sampling_dist(policy, legal_mask, n_legal=3)
        np.testing.assert_allclose(q[:3], policy[:3], atol=1e-5)
        assert q[3] == 0.0

    def test_epsilon_full_is_uniform(self):
        t = self._tvr(eps=1.0)
        policy = np.array([0.1, 0.3, 0.6, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, True, False])
        q = t._sampling_dist(policy, legal_mask, n_legal=3)
        # Uniform over 3 legal
        np.testing.assert_allclose(q[:3], [1 / 3, 1 / 3, 1 / 3], atol=1e-5)

    def test_mixed_epsilon(self):
        t = self._tvr(eps=0.5)
        policy = np.array([0.0, 0.5, 0.5, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, True, False])
        q = t._sampling_dist(policy, legal_mask, n_legal=3)
        # Expected: 0.5 * [1/3, 1/3, 1/3] + 0.5 * [0, 0.5, 0.5]
        # = [1/6, 1/6 + 1/4, 1/6 + 1/4] = [0.1667, 0.4167, 0.4167]
        expected = np.array([1 / 6, 1 / 6 + 1 / 4, 1 / 6 + 1 / 4])
        expected = expected / expected.sum()
        np.testing.assert_allclose(q[:3], expected, atol=1e-4)

    def test_sums_to_one_over_legal(self):
        # policy must sum to 1 over legal slots (invariant from
        # regret_to_policy upstream). q inherits that property.
        t = self._tvr(eps=0.3)
        policy = np.array([0.6, 0.4, 0.0, 0.0], dtype=np.float32)
        legal_mask = np.array([True, True, False, False])
        q = t._sampling_dist(policy, legal_mask, n_legal=2)
        assert abs(q[:2].sum() - 1.0) < 1e-5
        assert q[2] == 0.0
        assert q[3] == 0.0


# --------------------------------------------------------------------------- #
# End-to-end traversal smoke test (uses real engine)


def _make_traverser(seed: int = 0):
    """Build a CFRTraverser wrapping a fresh AdvantageNet + fresh buffers
    sized for the smoke game (赤蝶 vs 墨客, 1v1). n_counter_slots is
    the engine's static-obs capacity (1832), not the active count
    (~282). The former is what the static-obs layout is padded to."""
    # Capacity matches AZ smoke_config's AgentConfig.n_counter_slots:
    # 2*6*128 + 2*140 + 16 = 1832. The engine reserves this many slots
    # regardless of active counter count this game.
    n_counter_slots = 2 * 6 * 128 + 2 * 140 + 16

    cfg = CFRNetConfig(
        n_counter_slots=n_counter_slots,
        n_hooks=N_HOOKS_CAP,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    torch.manual_seed(seed)
    net = AdvantageNet(cfg)
    net.eval()
    return CFRTraverser(
        advantage_nets=[net, AdvantageNet(cfg)],
        n_counter_slots=n_counter_slots,
        max_ops_per_hook=MAX_TOK,
        n_hooks_capacity=N_HOOKS_CAP,
        max_actions=MAX_ACTIONS,
        advantage_buffers=[
            AdvantageBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
            AdvantageBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
        ],
        strategy_buffer=StrategyBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
        value_buffer=ValueBuffer(capacity=BUFFER_CAP),
        rng=random.Random(seed),
    )
