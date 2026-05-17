"""Tests for training/train.py — AZ train_step.

The buffer is used as the canonical batch producer so these tests
exercise the realistic shape contract between buffer → forward_batch
→ az_losses → backward → optimizer.step.
"""

from __future__ import annotations

import random

import numpy as np
import pytest
import torch

from training.core.obs_constants import (
    ACTION_END_TURN,
    ACTION_SKILL,
)
from training.paradigms.az.buffer import ReplayBuffer
from training.paradigms.az.network import (
    Agent,
    AgentConfig,
)
from training.paradigms.az.train_step import TrainStepConfig, train_step


# Small shapes for fast tests
N_SLOTS = 128
N_HOOKS = 8
MAX_TOK = 16
MAX_ACTIONS = 6
D_MODEL = 16


# Round-6 S-3: 共享 typed obs padding helper (替原 Round-5 inline)
from training.tests._typed_obs_fixtures import (  # noqa: E402
    make_modifier_log_padding_np as _make_modifier_log_padding,
    make_recent_damage_padding_np as _make_recent_damage_padding,
)


def _agent(seed: int = 0) -> Agent:
    torch.manual_seed(seed)
    cfg = AgentConfig(
        n_counter_slots=N_SLOTS,
        n_hooks=N_HOOKS,
        max_tokens_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    return Agent(cfg, lr=1e-2)


def _game_static(rng: np.random.RandomState):
    return {
        'hook_types': rng.randint(1, 100, (N_HOOKS, MAX_TOK)).astype(np.int64),
        'hook_values': np.zeros((N_HOOKS, MAX_TOK), dtype=np.float32),
        'hook_mask': np.ones(N_HOOKS, dtype=bool),
        'counter_sids': np.arange(N_SLOTS, dtype=np.int64),
        'active_slot_mask': np.ones(N_SLOTS, dtype=bool),
        'char_skill_refs': -np.ones((2, 6, 10), dtype=np.int64),
    }


def _step(
    rng: np.random.RandomState,
    *,
    z: float = 0.0,
    pi_legal_count: int = 3,
    is_discovery: bool = False,
):
    pi = np.zeros(MAX_ACTIONS, dtype=np.float32)
    pi[:pi_legal_count] = 1.0 / pi_legal_count

    legal = np.zeros(MAX_ACTIONS, dtype=bool)
    legal[:pi_legal_count] = True

    refs = np.full((MAX_ACTIONS, 3), -1, dtype=np.int64)
    refs[:, 0] = ACTION_END_TURN  # padding
    refs[0] = np.array([ACTION_SKILL, 0, -1], dtype=np.int64)
    refs[1] = np.array([ACTION_SKILL, 1, -1], dtype=np.int64)
    refs[2] = np.array([ACTION_SKILL, 2, -1], dtype=np.int64)

    return {
        'counter_values': rng.randn(N_SLOTS).astype(np.float32),
        'counter_target': rng.randn(N_SLOTS).astype(np.float32),
        'has_counter_target': True,
        'meta': np.array([3.0, 1.0, 1.0], dtype=np.float32),
        'card_buckets': np.zeros((4, 80), dtype=np.float32),
        'enemy_sizes': np.zeros(2, dtype=np.float32),
        # ADR-0019 §B.2/§B.3c typed obs segments — Round-5 S2: 与 engine
        # encode_*_padding 一致(categorical=-2,scalar=0;prepare_skill=-1
        # 真值"no prepare")。之前用 zeros 让 categorical=0 被 encoder
        # 解读成"perspective=self,P0,ElemNone,ModBoost"等真值,fixture
        # 跟生产分布偏离。
        'recent_damage': _make_recent_damage_padding(),
        'prepare_skill': np.full((2, 2), -1.0, dtype=np.float32),
        'modifier_log': _make_modifier_log_padding(),
        'action_refs': refs,
        'action_payments': np.zeros((MAX_ACTIONS, 8), dtype=np.float32),
        'legal_mask': legal,
        'pi_target': pi,
        'z_target': float(z),
        'is_discovery': is_discovery,
    }


def _buffer_with(n_games: int, steps_per_game: int, z_values=None, seed: int = 0):
    rb = ReplayBuffer(capacity=10_000)
    rng = np.random.RandomState(seed)
    for g in range(n_games):
        z = float(z_values[g]) if z_values is not None else 0.0
        steps = [_step(rng, z=z) for _ in range(steps_per_game)]
        rb.add_trajectory(_game_static(rng), steps)
    return rb


class TestTrainStepBasic:
    def test_single_step_returns_finite_losses(self):
        agent = _agent()
        rb = _buffer_with(n_games=2, steps_per_game=4)
        batch = rb.sample(8, random.Random(0))
        stats = train_step(agent, batch, TrainStepConfig())
        for k in ('total', 'value', 'policy', 'l2'):
            assert k in stats
            assert np.isfinite(stats[k]), f'{k} not finite: {stats[k]}'
        assert stats['total'] > 0
        assert stats['l2'] > 0

    def test_grads_populated_and_finite(self):
        agent = _agent()
        rb = _buffer_with(n_games=2, steps_per_game=4)
        batch = rb.sample(8, random.Random(0))
        train_step(agent, batch, TrainStepConfig())
        # After one step, every parameter that had gradient flow should
        # have .grad set. Value head + state_proj are easy probes.
        # Post core-network-generic-promotion Phase 2A: heads live in
        # net.heads ModuleDict; ValueHead inner Sequential is .head.
        g_val = agent.net.heads['value'].head[0].weight.grad
        g_state = agent.net.state_proj[0].weight.grad
        assert g_val is not None and torch.isfinite(g_val).all()
        assert g_state is not None and torch.isfinite(g_state).all()

    def test_typed_damage_encoder_grads_populated(self):
        """Round-3 review S9: typed_damage_encoder.* must receive
        gradient flow. If a future refactor accidentally detaches the
        typed_pool or zeros it out before reaching state_proj,
        downstream tests still pass but typed signal goes dead.
        Catch this by asserting EVERY parameter under
        typed_damage_encoder has a finite, set gradient."""
        agent = _agent()
        rb = _buffer_with(n_games=2, steps_per_game=4)
        batch = rb.sample(8, random.Random(0))
        train_step(agent, batch, TrainStepConfig())
        # Post core-network-generic-promotion Phase 2A: typed_damage_encoder
        # renamed to typed_damage (composition-style attribute).
        encoder = agent.net.typed_damage
        for name, p in encoder.named_parameters():
            assert p.grad is not None, f'typed_damage.{name}.grad is None — typed_pool likely detached'
            assert torch.isfinite(p.grad).all(), f'typed_damage.{name}.grad has non-finite values'

    def test_save_load_roundtrip_forward_consistent(self):
        """Round-3 review S10 + Round-4 M-1 修复:save → load(strict=True)
        → forward must produce identical outputs. ADR-0019 added 7
        nn.Embedding + multiple nn.Sequential under typed_damage_encoder;
        this test guards against accidental module-naming drift that
        would let save succeed but strict-load fail.

        Round-4 M-1: 之前 `_forward_value(net)` 闭包捕获外层 `agent`
        让 `loaded_value` 实际仍调 `agent.forward_batch`(忽略 net 参数),
        断言变 tautology — agent2.load 是 no-op 也能过。修法是参数化
        agent 而非 net,显式调用对应 agent 的 forward_batch。"""
        import tempfile

        agent = _agent(seed=42)
        rb = _buffer_with(n_games=1, steps_per_game=4, seed=99)
        batch = rb.sample(4, random.Random(0))

        # Force eval mode for deterministic comparison (dropout off)
        agent.net.eval()

        def _forward_value(a):
            """Run forward_batch on the given agent; return value tensor."""
            with torch.no_grad():
                return a.forward_batch(batch)[1].clone()

        base_value = _forward_value(agent)

        with tempfile.NamedTemporaryFile(suffix='.pt', delete=False) as f:
            ckpt_path = f.name
        try:
            agent.save(ckpt_path)
            agent2 = _agent(seed=0)  # different init — load must overwrite
            agent2.load(ckpt_path)
            agent2.net.eval()
            loaded_value = _forward_value(agent2)
            assert torch.allclose(base_value, loaded_value, atol=1e-6), (
                f'save/load round-trip altered forward output: '
                f'base={base_value} loaded={loaded_value}. '
                'Likely strict-load missed a parameter or buffer.'
            )
        finally:
            import os

            os.unlink(ckpt_path)

    def test_value_head_overfits_tiny_set(self):
        """Given a fixed 4-step batch with z_target=+1 on all, the
        value head should learn to produce value ≈ +1 after a few
        hundred steps. This verifies the gradient actually updates
        the weights in the expected direction, not just that the
        code runs."""
        agent = _agent(seed=7)
        rng = np.random.RandomState(11)
        rb = ReplayBuffer(capacity=100)
        steps = [_step(rng, z=1.0) for _ in range(4)]
        rb.add_trajectory(_game_static(rng), steps)

        cfg = TrainStepConfig(l2_coef=0.0, max_grad_norm=0.0)
        initial_stats = None
        final_stats = None
        for step in range(300):
            batch = rb.sample(4, random.Random(0))  # same batch every call
            stats = train_step(agent, batch, cfg)
            if step == 0:
                initial_stats = stats
            final_stats = stats

        # Value loss should have dropped noticeably.
        assert final_stats['value'] < initial_stats['value'] * 0.5, (
            f'value loss did not overfit: initial={initial_stats["value"]:.4f}, final={final_stats["value"]:.4f}'
        )


class TestValueTargetSource:
    def _batch_with_mcts_value(self, n=4, seed=0):
        rb = _buffer_with(n_games=1, steps_per_game=n)
        batch = rb.sample(n, random.Random(seed))
        # Bolt mcts_value onto the batch — self-play worker will do this
        # once we add the field to step_dict (currently optional).
        batch['mcts_value'] = np.full(n, 0.7, dtype=np.float32)
        return batch

    def test_z_default(self):
        agent = _agent()
        batch = self._batch_with_mcts_value()
        stats_z = train_step(agent, batch, TrainStepConfig(value_target_source='z'))
        assert np.isfinite(stats_z['value'])

    def test_mcts_value(self):
        agent = _agent()
        batch = self._batch_with_mcts_value()
        stats = train_step(agent, batch, TrainStepConfig(value_target_source='mcts_value'))
        assert np.isfinite(stats['value'])

    def test_mixed(self):
        agent = _agent()
        batch = self._batch_with_mcts_value()
        stats = train_step(
            agent,
            batch,
            TrainStepConfig(value_target_source='mixed', value_mix_lambda=0.3),
        )
        assert np.isfinite(stats['value'])

    def test_mcts_value_missing_field_raises(self):
        agent = _agent()
        rb = _buffer_with(n_games=1, steps_per_game=4)
        batch = rb.sample(4, random.Random(0))  # no mcts_value
        with pytest.raises(KeyError, match='mcts_value'):
            train_step(agent, batch, TrainStepConfig(value_target_source='mcts_value'))

    def test_unknown_source_raises(self):
        agent = _agent()
        rb = _buffer_with(n_games=1, steps_per_game=4)
        batch = rb.sample(4, random.Random(0))
        with pytest.raises(ValueError, match='unknown value_target_source'):
            train_step(agent, batch, TrainStepConfig(value_target_source='garbage'))


class TestNaNGuard:
    def test_nan_loss_raises_before_optim_step(self, monkeypatch):
        """Inject a NaN into the loss tensor and assert train_step
        raises BEFORE calling optimizer.step. Catches the whole
        class of divergence bugs that would otherwise poison the
        optimizer state and only surface hours later."""
        import training.paradigms.az.train_step as train_mod

        agent = _agent(seed=0)
        rb = _buffer_with(n_games=1, steps_per_game=4)
        batch = rb.sample(4, random.Random(1))

        original_net_forward = agent.net.forward

        def forward_nan(*args, **kwargs):
            # Post core-network-generic-promotion Phase 2A: net.forward
            # returns dict {policy, value, delta, _state_vec, ...} not
            # 3-tuple. Inject NaN into the 'value' tensor and return the
            # same dict so callers (forward_batch unpacks via dict keys)
            # see the poisoned value scalar.
            out = original_net_forward(*args, **kwargs)
            out['value'] = out['value'] + float('nan')
            return out

        monkeypatch.setattr(agent.net, 'forward', forward_nan)

        # Record the optimizer step call count.
        calls = {'n': 0}
        real_step = agent.optimizer.step

        def wrapped_step(*a, **kw):
            calls['n'] += 1
            return real_step(*a, **kw)

        agent.optimizer.step = wrapped_step  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match='non-finite'):
            train_step(agent, batch, TrainStepConfig())
        assert calls['n'] == 0, 'optimizer.step must NOT run when loss is NaN'


class TestGradClip:
    def test_clip_bounds_grad_norm(self):
        """With max_grad_norm=1.0, after backward the norm of any
        parameter's grad × its count can't exceed ~1.0 total. We
        check the overall grad norm is bounded."""
        agent = _agent()
        rb = _buffer_with(n_games=4, steps_per_game=8)
        batch = rb.sample(16, random.Random(0))
        train_step(agent, batch, TrainStepConfig(max_grad_norm=1.0))
        # After train_step the optimizer has stepped, but grads are
        # still on the parameters. Compute total norm and verify
        # it was clipped. We re-run forward/backward without stepping
        # to inspect — easier: set lr=0 by using a fresh agent and a
        # clip of 0.5, then manually forward+backward without train_step.
        # But that's a lot of setup; a simpler check: after train_step
        # the grads reflect the POST-clip state, so compute the L2
        # norm and ensure it's bounded by max_grad_norm.
        total = 0.0
        for p in agent.net.parameters():
            if p.grad is not None:
                total += p.grad.detach().norm().item() ** 2
        total_norm = total**0.5
        # Allow a little slack because the clip is applied BEFORE
        # optim.step but the norm we measure is the one that went
        # into step(); pytorch's clip_grad_norm_ scales in-place.
        assert total_norm <= 1.0 + 1e-4, f'post-clip grad norm {total_norm} exceeds cap 1.0'
