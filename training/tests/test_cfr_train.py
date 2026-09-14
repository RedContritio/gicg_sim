"""Tests for training/paradigms/cfr/legacy/train.py — smoke / contract level only.

Numerical convergence on real game scale is tens-of-minutes compute,
not appropriate for pytest. Here we verify the loop closes, buffers
fill, losses are finite numbers, and checkpoint save/load survive.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.cfr import CFRNetConfig, CFRStrategyNet
from training.paradigms.cfr.train import CFRTrainConfig, CFRTrainer
from training.paradigms.cfr.traversal import TraversalConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


D_MODEL = 8
MAX_TOK = 128
N_HOOKS_CAP = 900
MAX_ACTIONS = 2048
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16  # = 1832


def _env_factory(seed: int) -> GicgEnv:
    env = GicgEnv(['赤蝶'], ['墨客'], seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    return env


def _net_cfg() -> CFRNetConfig:
    return CFRNetConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS_CAP,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )


def _train_cfg(**overrides) -> CFRTrainConfig:
    cfg = CFRTrainConfig(
        n_iterations=2,
        traversals_per_iteration=2,
        advantage_fit_steps_per_iter=2,
        strategy_fit_steps=2,
        strategy_fit_every=1,
        fit_batch_size=4,
        advantage_buffer_capacity=128,
        strategy_buffer_capacity=128,
        value_buffer_capacity=128,
        checkpoint_every=0,  # disable saves for tests that don't set tmp dir
        traversal=TraversalConfig(max_game_steps=400, epsilon=0.2),
        seed=13,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# --------------------------------------------------------------------------- #
# Smoke: one iteration closes without crash


class TestTrainerOneIteration:
    def test_iteration_zero_skips_strategy_fit(self):
        """iter=0 should skip strategy/value fit — buffer is still
        near-empty after 1 iter of traversals. Advantage fit still
        runs (its buffer just got its first samples)."""
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        m = trainer.run_iteration(0)
        assert m.iteration == 0
        assert m.n_traversals == 2
        assert np.isfinite(m.advantage_loss)
        # Strategy / value fits are explicitly skipped at iter 0.
        assert m.strategy_loss is None
        assert m.value_loss is None
        # Buffers have received samples from the 2 traversals. With
        # per-player nets and alternating traverser, both adv_p0 and
        # adv_p1 should be non-empty.
        assert m.buffer_sizes['advantage_p0'] > 0
        assert m.buffer_sizes['advantage_p1'] > 0
        assert m.buffer_sizes['strategy'] > 0
        assert m.buffer_sizes['value'] > 0

    def test_iteration_one_runs_strategy_fit(self):
        """iter>=1 with strategy_fit_every=1 triggers the joint
        policy+value fit. Both losses should be present + finite."""
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        trainer.run_iteration(0)
        m = trainer.run_iteration(1)
        assert m.strategy_loss is not None
        assert m.value_loss is not None
        assert np.isfinite(m.strategy_loss)
        assert np.isfinite(m.value_loss)

    def test_alternate_mode_picks_both_sides(self):
        """_pick_traverser('alternate', k) should return 0 for even k
        and 1 for odd k. Unit-test the function directly rather than
        inferring from buffer state."""
        cfg = _train_cfg()
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        # k=0,2,4 → 0; k=1,3 → 1
        assert trainer._pick_traverser(0, 0) == 0
        assert trainer._pick_traverser(0, 1) == 1
        assert trainer._pick_traverser(0, 2) == 0
        assert trainer._pick_traverser(0, 3) == 1

    def test_random_alternation_runs(self):
        cfg = _train_cfg(traverser_alternation='random')
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        trainer.run_iteration(0)  # no crash

    def test_unknown_alternation_raises(self):
        cfg = _train_cfg(traverser_alternation='bogus')
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        with pytest.raises(ValueError, match='traverser_alternation'):
            trainer.run_iteration(0)


class TestTrainerMultiIteration:
    def test_two_iterations_run_cleanly(self):
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        metrics = trainer.train()
        assert len(metrics) == 2
        for m in metrics:
            assert np.isfinite(m.advantage_loss)

    def test_advantage_reset_swaps_net_object_and_updates_traverser(self):
        """With reset=True, iter>0 reinitializes advantage_net (new
        object id) and the traverser must continue pointing at the
        new net. Without reset, the net object is stable across
        iterations."""
        # With reset — check each per-player net swapped.
        cfg = _train_cfg(advantage_reset_each_iter=True)
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        trainer.run_iteration(0)
        ids_after_0 = [id(n) for n in trainer.advantage_nets]
        trainer.run_iteration(1)
        ids_after_1 = [id(n) for n in trainer.advantage_nets]
        for p in range(2):
            assert ids_after_0[p] != ids_after_1[p], f'advantage_nets[{p}] should be fresh after reset in iter 1'
        # Traverser must use the new nets
        for p in range(2):
            assert trainer.traverser.advantage_nets[p] is trainer.advantage_nets[p], (
                f'traverser.advantage_nets[{p}] lost sync after reset'
            )

        # Without reset: same nets persist
        cfg2 = _train_cfg(advantage_reset_each_iter=False)
        trainer2 = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg2,
            env_factory=_env_factory,
        )
        trainer2.run_iteration(0)
        ids2_0 = [id(n) for n in trainer2.advantage_nets]
        trainer2.run_iteration(1)
        ids2_1 = [id(n) for n in trainer2.advantage_nets]
        for p in range(2):
            assert ids2_0[p] == ids2_1[p], f'advantage_nets[{p}] should NOT be swapped when reset=False'


# --------------------------------------------------------------------------- #
# Checkpoint


class TestCheckpoint:
    def test_checkpoint_writes_and_loads(self, tmp_path):
        cfg = _train_cfg(
            checkpoint_every=1,
            checkpoint_dir=str(tmp_path),
        )
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        trainer.train()
        files = sorted(tmp_path.glob('cfr_strategy_iter*.pt'))
        assert files, 'no checkpoint written'
        # Load into fresh strategy net
        restored = CFRStrategyNet(_net_cfg())
        restored.load(str(files[-1]))
        # Compare forward on a dummy batch — weights should match
        for p_orig, p_rest in zip(
            trainer.strategy_net.parameters(),
            restored.parameters(),
        ):
            torch.testing.assert_close(
                p_orig.detach().cpu(),
                p_rest.detach().cpu(),
                atol=1e-6,
                rtol=1e-6,
            )

    def test_save_returns_none_when_dir_missing(self):
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),  # checkpoint_dir=None
            env_factory=_env_factory,
        )
        assert trainer.save_checkpoint(0) is None


# --------------------------------------------------------------------------- #
# Loss finiteness + learning signal


class TestGradientFlow:
    def test_hook_encoder_receives_gradient_on_advantage_fit(self):
        """hook_encoder lives in the trunk; reservoir stores raw hook
        tokens; fit path re-runs hook_encoder inside
        _forward_batch (so it's on the backward graph). Verify at
        least one hook_encoder param has nonzero grad after a fit."""
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        # Collect traversal samples
        trainer._run_traversals(0)
        from training.paradigms.cfr.fit_steps import fit_advantage

        fit_advantage(trainer, 0)
        got_grad = False
        for p in trainer.advantage_nets[0].trunk.hook_encoder.parameters():
            if p.grad is not None and p.grad.abs().sum() > 0:
                got_grad = True
                break
        assert got_grad, 'hook_encoder params did not receive grad'

    def test_clip_grads_respects_max_norm(self):
        """Test clip_grads directly on a synthetic gradient larger
        than max_norm. After clip, the parameters' gradient L2 norm
        must equal max_norm (within float slack)."""
        from training.paradigms.cfr.fit_steps import clip_grads

        cfg = _train_cfg(grad_clip_max_norm=0.1)
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        # Stuff a large synthetic gradient into advantage_net.
        for p in trainer.advantage_nets[0].parameters():
            p.grad = torch.ones_like(p) * 10.0
        clip_grads(trainer, trainer.advantage_nets[0])
        grads = [p.grad for p in trainer.advantage_nets[0].parameters() if p.grad is not None]
        total_norm = torch.sqrt(sum(g.pow(2).sum() for g in grads)).item()
        assert abs(total_norm - 0.1) < 1e-4, f'post-clip norm {total_norm:.6f} != max_norm 0.1'

    def test_clip_grads_disabled_at_zero(self):
        """grad_clip_max_norm=0 means no clipping."""
        from training.paradigms.cfr.fit_steps import clip_grads

        cfg = _train_cfg(grad_clip_max_norm=0.0)
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=cfg,
            env_factory=_env_factory,
        )
        for p in trainer.advantage_nets[0].parameters():
            p.grad = torch.ones_like(p) * 10.0
        clip_grads(trainer, trainer.advantage_nets[0])
        # Grads should be untouched (still 10.0 elementwise)
        sample = next(trainer.advantage_nets[0].parameters()).grad
        assert (sample == 10.0).all()


class TestLossSanity:
    def test_advantage_loss_is_nonnegative(self):
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        m = trainer.run_iteration(0)
        assert m.advantage_loss >= 0.0

    def test_strategy_ce_loss_is_nonnegative(self):
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        trainer.run_iteration(0)
        m = trainer.run_iteration(1)  # strategy fit only runs on iter >= 1
        assert m.strategy_loss is not None
        assert m.strategy_loss >= 0.0

    def test_value_mse_loss_is_finite(self):
        trainer = CFRTrainer(
            net_cfg=_net_cfg(),
            train_cfg=_train_cfg(),
            env_factory=_env_factory,
        )
        trainer.run_iteration(0)
        m = trainer.run_iteration(1)
        assert m.value_loss is not None
        assert np.isfinite(m.value_loss)
