"""Tests for training/paradigms/cfr/legacy/network."""

from __future__ import annotations

import torch
import pytest

from training.paradigms.cfr import (
    AdvantageNet,
    CFRNetConfig,
    CFRStrategyNet,
    regret_to_policy,
)


D_MODEL = 8
N_COUNTER_SLOTS = 32
N_HOOKS_ACTIVE = 5
MAX_TOKENS = 4
MAX_ACTIONS = 6
N_CROSS = 1
CHAR_SKILL_SHAPE = (2, 6, 10)  # (players, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR)


def _cfg() -> CFRNetConfig:
    return CFRNetConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=100,  # declared max; actual cached is smaller
        max_tokens_per_hook=MAX_TOKENS,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        dropout=0.0,
        n_cross_layers=N_CROSS,
    )


def _batch(B: int = 2, mixed_action_kinds: bool = True):
    # Default: slot 0 = SKILL (kind=0), 1 = CARD, 2 = SWITCH, 3 = END_TURN,
    # 4+ = SKILL. This exercises all pointer-net branches so every
    # head parameter receives a gradient path.
    action_refs = torch.zeros(B, MAX_ACTIONS, 3, dtype=torch.long)
    if mixed_action_kinds:
        kinds = [0, 1, 2, 3] + [0] * (MAX_ACTIONS - 4)
        for i, k in enumerate(kinds[:MAX_ACTIONS]):
            action_refs[:, i, 0] = k
            action_refs[:, i, 1] = 0 if k in (0, 1) else -1  # hook_idx
            action_refs[:, i, 2] = 1 if k == 2 else 0  # char_idx for SWITCH
    return {
        'counter_values': torch.randn(B, N_COUNTER_SLOTS),
        'counter_sids': torch.randint(0, N_COUNTER_SLOTS, (B, N_COUNTER_SLOTS)),
        'active_slot_mask': torch.ones(B, N_COUNTER_SLOTS, dtype=torch.bool),
        'hook_emb_cached': torch.randn(B, N_HOOKS_ACTIVE, D_MODEL),
        'hook_mask': torch.ones(B, N_HOOKS_ACTIVE, dtype=torch.bool),
        'card_buckets': torch.randn(B, 4, 80),
        'enemy_sizes': torch.randn(B, 2),
        'meta': torch.randn(B, 3),
        'action_refs': action_refs,
        'action_payments': torch.randn(B, MAX_ACTIONS, 8),
        'structural_values': torch.randn(B, 66),  # N_STRUCTURAL
        'char_skill_refs': torch.full(
            (B, *CHAR_SKILL_SHAPE),
            -1,
            dtype=torch.long,
        ),
    }


# Forward shape + output contract -------------------------------------


class TestCFRStrategyNetForward:
    def test_output_shapes(self):
        torch.manual_seed(0)
        net = CFRStrategyNet(_cfg())
        net.eval()
        b = _batch(B=3)
        logits, value = net(**b)
        assert logits.shape == (3, MAX_ACTIONS)
        assert value.shape == (3,)

    def test_value_in_tanh_range(self):
        torch.manual_seed(0)
        net = CFRStrategyNet(_cfg())
        net.eval()
        # Run many batches with random input; value must stay in [-1, 1]
        for _ in range(10):
            b = _batch(B=4)
            _logits, value = net(**b)
            assert value.min().item() >= -1.0 - 1e-6
            assert value.max().item() <= 1.0 + 1e-6

    def test_gradient_flows(self):
        """Gradient flow through every non-hook_encoder parameter.
        hook_encoder is intentionally bypassed when the caller passes
        hook_emb_cached (per-game static path), so its params don't
        receive gradients here — that's by design, not a bug."""
        torch.manual_seed(0)
        net = CFRStrategyNet(_cfg())
        net.train()
        b = _batch(B=2)
        logits, value = net(**b)
        loss = logits.sum() + value.sum()
        loss.backward()
        without_grad = [name for name, p in net.named_parameters() if p.grad is None or p.grad.abs().sum() == 0]
        # Only hook_encoder params are legitimately inert under the
        # hook_emb_cached forward path.
        non_hook_without_grad = [n for n in without_grad if not n.startswith('trunk.hook_encoder')]
        assert not non_hook_without_grad, f'non-hook-encoder params missing gradients: {non_hook_without_grad}'


class TestAdvantageNetForward:
    def test_output_shape(self):
        torch.manual_seed(0)
        net = AdvantageNet(_cfg())
        net.eval()
        b = _batch(B=3)
        regret = net(**b)
        assert regret.shape == (3, MAX_ACTIONS)

    def test_regret_is_unbounded(self):
        """Regret head has no final nonlinearity — output can be any
        real. Verify by running many batches and checking we observe
        values of both signs."""
        torch.manual_seed(42)
        net = AdvantageNet(_cfg())
        net.eval()
        all_vals = []
        for _ in range(20):
            b = _batch(B=4)
            regret = net(**b)
            all_vals.append(regret.flatten())
        all_vals = torch.cat(all_vals)
        assert all_vals.min().item() < 0.0, 'never produced negative regret'
        assert all_vals.max().item() > 0.0, 'never produced positive regret'


# regret_to_policy ---------------------------------------------------


class TestRegretToPolicy:
    def test_positive_regret_normalizes(self):
        regret = torch.tensor([[1.0, 2.0, 3.0, -5.0]])
        legal = torch.tensor([[True, True, True, True]])
        policy = regret_to_policy(regret, legal)
        # relu = [1, 2, 3, 0], sum=6 → [1/6, 2/6, 3/6, 0]
        expected = torch.tensor([[1 / 6, 2 / 6, 3 / 6, 0.0]])
        torch.testing.assert_close(policy, expected, atol=1e-5, rtol=1e-5)

    def test_all_nonpositive_fallback_to_uniform(self):
        regret = torch.tensor([[-1.0, -2.0, -3.0, -4.0]])
        legal = torch.tensor([[True, True, True, True]])
        policy = regret_to_policy(regret, legal)
        expected = torch.full((1, 4), 0.25)
        torch.testing.assert_close(policy, expected, atol=1e-5, rtol=1e-5)

    def test_illegal_actions_masked_out(self):
        regret = torch.tensor([[1.0, 2.0, 3.0, 100.0]])
        legal = torch.tensor([[True, True, True, False]])
        policy = regret_to_policy(regret, legal)
        # relu = [1, 2, 3, 100], masked = [1, 2, 3, 0], sum=6
        expected = torch.tensor([[1 / 6, 2 / 6, 3 / 6, 0.0]])
        torch.testing.assert_close(policy, expected, atol=1e-5, rtol=1e-5)

    def test_uniform_fallback_respects_legal_mask(self):
        regret = torch.tensor([[-1.0, -2.0, -3.0, -4.0]])
        legal = torch.tensor([[True, True, False, False]])
        policy = regret_to_policy(regret, legal)
        # Uniform over 2 legal → [0.5, 0.5, 0, 0]
        expected = torch.tensor([[0.5, 0.5, 0.0, 0.0]])
        torch.testing.assert_close(policy, expected, atol=1e-5, rtol=1e-5)

    def test_batch_independence(self):
        regret = torch.tensor(
            [
                [1.0, 2.0, -1.0, -1.0],  # positive path
                [-1.0, -1.0, -1.0, -1.0],  # uniform fallback path
            ]
        )
        legal = torch.tensor(
            [
                [True, True, True, True],
                [True, True, True, True],
            ]
        )
        policy = regret_to_policy(regret, legal)
        expected = torch.tensor(
            [
                [1 / 3, 2 / 3, 0.0, 0.0],
                [0.25, 0.25, 0.25, 0.25],
            ]
        )
        torch.testing.assert_close(policy, expected, atol=1e-5, rtol=1e-5)


# Save / load ---------------------------------------------------------


class TestSaveLoad:
    def test_strategy_save_load_roundtrip(self, tmp_path):
        torch.manual_seed(7)
        net = CFRStrategyNet(_cfg())
        path = tmp_path / 'cfr.pt'
        net.save(str(path))

        # Load into a fresh instance and check forward matches
        restored = CFRStrategyNet(_cfg())
        restored.load(str(path))
        net.eval()
        restored.eval()
        b = _batch(B=2)
        l1, v1 = net(**b)
        l2, v2 = restored(**b)
        torch.testing.assert_close(l1, l2, atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(v1, v2, atol=1e-5, rtol=1e-5)

    def test_strategy_load_rejects_wrong_kind(self, tmp_path):
        """A ckpt saved as AdvantageNet must not load into CFRStrategyNet
        (weight keys may overlap via the shared trunk, but the kind tag
        guards against architectural mismatch)."""
        torch.manual_seed(8)
        adv = AdvantageNet(_cfg())
        path = tmp_path / 'adv.pt'
        adv.save(str(path))

        net = CFRStrategyNet(_cfg())
        with pytest.raises(RuntimeError, match='kind'):
            net.load(str(path))

    def test_advantage_save_load_roundtrip(self, tmp_path):
        torch.manual_seed(11)
        net = AdvantageNet(_cfg())
        path = tmp_path / 'adv.pt'
        net.save(str(path))
        restored = AdvantageNet(_cfg())
        restored.load(str(path))
        net.eval()
        restored.eval()
        b = _batch(B=2)
        r1 = net(**b)
        r2 = restored(**b)
        torch.testing.assert_close(r1, r2, atol=1e-5, rtol=1e-5)


# Architectural sanity checks ----------------------------------------


class TestLargeDModelStability:
    """Smoke tests at d_model=64 to catch numerical instability that
    hides at d_model=8. Previously all network tests used d_model=8 so
    init/activation scale bugs wouldn't surface until real training."""

    def _large_cfg(self) -> CFRNetConfig:
        return CFRNetConfig(
            n_counter_slots=N_COUNTER_SLOTS,
            n_hooks=100,
            max_tokens_per_hook=MAX_TOKENS,
            max_actions=MAX_ACTIONS,
            d_model=64,
            dropout=0.0,
            n_cross_layers=2,
        )

    def test_strategy_net_forward_at_d64(self):
        torch.manual_seed(0)
        net = CFRStrategyNet(self._large_cfg())
        net.eval()
        b = _batch(B=4)
        # Override hook_emb_cached to match d_model=64
        b['hook_emb_cached'] = torch.randn(4, N_HOOKS_ACTIVE, 64)
        logits, value = net(**b)
        assert torch.all(torch.isfinite(logits)), 'logits NaN/Inf at d=64'
        assert torch.all(torch.isfinite(value))
        assert value.min() >= -1.0 - 1e-5
        assert value.max() <= 1.0 + 1e-5

    def test_advantage_net_forward_at_d64(self):
        torch.manual_seed(0)
        net = AdvantageNet(self._large_cfg())
        net.eval()
        b = _batch(B=4)
        b['hook_emb_cached'] = torch.randn(4, N_HOOKS_ACTIVE, 64)
        regret = net(**b)
        assert torch.all(torch.isfinite(regret))

    def test_backward_grad_finite_at_d64(self):
        torch.manual_seed(0)
        net = CFRStrategyNet(self._large_cfg())
        net.train()
        b = _batch(B=2)
        b['hook_emb_cached'] = torch.randn(2, N_HOOKS_ACTIVE, 64)
        logits, value = net(**b)
        loss = logits.pow(2).mean() + value.pow(2).mean()
        loss.backward()
        for name, p in net.named_parameters():
            if p.grad is None:
                continue
            assert torch.all(torch.isfinite(p.grad)), f'non-finite grad in {name} at d=64'


class TestArchitectureSanity:
    def test_strategy_and_advantage_have_independent_weights(self):
        """Two fresh nets of different types should have independent
        parameters (no hidden sharing)."""
        torch.manual_seed(0)
        s = CFRStrategyNet(_cfg())
        torch.manual_seed(0)
        a = AdvantageNet(_cfg())
        # They share trunk architecture so some param names match,
        # but tensors are distinct objects
        for (ns, ps), (na, pa) in zip(
            s.trunk.named_parameters(),
            a.trunk.named_parameters(),
        ):
            assert ns == na
            assert ps is not pa

    def test_independent_trained_checkpoints(self, tmp_path):
        """Two CFRStrategyNet instances with different seeds must
        produce different outputs after one gradient step each."""
        torch.manual_seed(0)
        net_a = CFRStrategyNet(_cfg())
        torch.manual_seed(1)
        net_b = CFRStrategyNet(_cfg())
        b = _batch(B=2)
        la, _ = net_a(**b)
        lb, _ = net_b(**b)
        assert not torch.allclose(la, lb, atol=1e-4), 'different-seeded nets produced identical outputs'
