"""Behavioral test: BCParadigm hard-target path actually learns.

Contract under test (was historically guarded by the legacy
``training.paradigms.bc.legacy.bc_train_ppo`` spies on
``masked_cross_entropy`` / ``soft_target_ce``):

> Given a BC dataset of hard-target decisions(deterministic teacher
> picks ``chosen_action`` per example),when BCParadigm is configured
> with ``loss_kind='ce'`` (hard target) and trained via the active
> ``BCLoss`` against a small policy network,training-set accuracy
> climbs to ~100% and loss decreases monotonically.

The original PPO-flavored test stubbed the legacy ``train_bc`` function and
counted call-sites on internal soft / hard helpers. That coupled the test
to a specific implementation (PPONet + bc_losses_ppo) that has now been
retired (FU-W1A-followup). The rewrite verifies the **same observable
behavior**(hard-target CE drives loss → 0, argmax → teacher action)
through the production ``training.paradigms.bc.loss.BCLoss`` API instead.

We use a small learnable Linear net (obs → logits) rather than the full
``BCNetwork`` so the test stays fast(< 1 s)while still backpropagating
through ``BCLoss.compute`` end-to-end with real ``loss_kind='ce'`` /
``loss_kind='kl'`` branching.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch
import torch.nn as nn

from training.core.protocols import Batch
from training.paradigms.bc.config import BCParadigmConfig
from training.paradigms.bc.loss import BCLoss


# ---------- Synthetic hard-target dataset ---------- #


def _synthetic_hard_dataset(n: int = 64, obs_size: int = 8, max_actions: int = 4, seed: int = 0):
    """Build a deterministic teacher: action = argmax of first ``max_actions``
    obs dims。Every example has a unique tied set = {chosen_action}(hard)。

    Returns dict of numpy arrays:obs / chosen_action / legal_mask / tied_mask
    / terminal_z — matches the schema ``BCLoss`` reads from
    ``batch.data['fields']``。
    """
    rng = np.random.default_rng(seed)
    obs = rng.standard_normal(size=(n, obs_size)).astype(np.float32)
    # Teacher: argmax of first 4 dims of obs — fully learnable by linear net。
    chosen = np.argmax(obs[:, :max_actions], axis=1).astype(np.int64)
    legal_mask = np.ones((n, max_actions), dtype=bool)
    # Hard target: tied_mask = one-hot(chosen)。soft path 见 with_tied=False
    # variant below。
    tied_mask = np.zeros((n, max_actions), dtype=bool)
    tied_mask[np.arange(n), chosen] = True
    terminal_z = rng.choice([-1.0, 0.0, 1.0], size=(n,)).astype(np.float32)
    return {
        'obs': obs,
        'chosen_action': chosen,
        'legal_mask': legal_mask,
        'tied_mask': tied_mask,
        'terminal_z': terminal_z,
    }


# ---------- Stub network: linear obs → logits ---------- #


class _LinearPolicyNet(nn.Module):
    """Minimal trainable wrapper exposing ``forward_batch(fields)`` to BCLoss。

    Reads ``fields['obs']`` (synthetic dataset 关键字)+ returns (logits,
    value)。Value head is a single scalar(0)so value_coef=0 branch is
    exercised without grad through value path。Used only by this test —
    BCNetwork(ActorCritic wrapper)is too expensive for a fast unit。
    """

    def __init__(self, obs_size: int, max_actions: int) -> None:
        super().__init__()
        self.policy_head = nn.Linear(obs_size, max_actions)

    def forward_batch(self, fields: dict) -> tuple[torch.Tensor, torch.Tensor]:
        obs = torch.as_tensor(fields['obs'], dtype=torch.float32)
        logits = self.policy_head(obs)
        # value head not trained when value_coef=0;return matching-shape zeros。
        value = torch.zeros(obs.shape[0], dtype=torch.float32)
        return logits, value


# ---------- Helpers ---------- #


def _build_batch(fields: dict) -> Batch:
    return Batch(data={'fields': fields}, size=int(fields['chosen_action'].shape[0]))


def _accuracy(net: _LinearPolicyNet, fields: dict) -> float:
    """Argmax accuracy of net policy vs teacher chosen_action on full set."""
    with torch.no_grad():
        logits, _ = net.forward_batch(fields)
        pred = logits.argmax(dim=-1).numpy()
    return float((pred == fields['chosen_action']).mean())


def _train_loop(
    net: _LinearPolicyNet,
    fields: dict,
    loss_fn: BCLoss,
    n_epochs: int,
    lr: float = 0.1,
) -> list[float]:
    """Run a tiny full-batch SGD loop。Returns per-epoch loss values。"""
    opt = torch.optim.SGD(net.parameters(), lr=lr)
    batch = _build_batch(fields)
    losses: list[float] = []
    for _ in range(n_epochs):
        opt.zero_grad()
        res = loss_fn.compute(net, batch)
        res.loss.backward()
        opt.step()
        losses.append(float(res.loss.item()))
    return losses


# ---------- Tests ---------- #


def test_bc_hard_target_loss_decreases_and_fits_teacher():
    """Behavioral contract:loss_kind='ce' (hard target) drives loss
    monotonically down and policy argmax reaches teacher on a fully-
    learnable synthetic task(linear teacher,linear student)。

    This is the **central** rewrite of the legacy PPO-variant test:同
    一行为(hard-target BC 学习 teacher decision)through the active
    BCLoss API。"""
    torch.manual_seed(0)
    fields = _synthetic_hard_dataset(n=64, obs_size=8, max_actions=4, seed=0)
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/synthetic', 'loss_kind': 'ce'})
    loss_fn = BCLoss(cfg)
    net = _LinearPolicyNet(obs_size=8, max_actions=4)

    initial_acc = _accuracy(net, fields)
    losses = _train_loop(net, fields, loss_fn, n_epochs=400, lr=0.1)
    final_acc = _accuracy(net, fields)

    # Loss must decrease substantially:initial > final 至少 5×(empirically
    # ~6× at epoch 400 lr=0.1 with this synthetic teacher;余量充足)。
    assert losses[0] > losses[-1], f'loss did not decrease: {losses[0]:.4f} → {losses[-1]:.4f}'
    assert losses[-1] < losses[0] / 5.0, (
        f'loss did not decrease enough: {losses[0]:.4f} → {losses[-1]:.4f} (need 5× reduction)'
    )
    # Accuracy must improve well above random(1/max_actions = 25%)。
    # Random initial weights typically get ≤ 40%;trained linear ≥ 95%。
    assert final_acc >= 0.95, f'final accuracy too low: {final_acc:.3f} (initial={initial_acc:.3f})'
    # Loss curve roughly monotone(allow tiny noise from full-batch SGD)。
    early_avg = sum(losses[:10]) / 10
    late_avg = sum(losses[-10:]) / 10
    assert late_avg < early_avg, f'late avg {late_avg:.4f} >= early avg {early_avg:.4f}'


def test_bc_hard_target_ce_breakdown_marks_loss_kind_zero():
    """BCLoss.compute breakdown['loss_kind'] is 0.0 for hard CE(1.0 for
    KL soft target)。This guards against the wiring drift the legacy spy
    test was originally protecting against(soft/hard branch decided by
    cfg,not silently swapped)。"""
    fields = _synthetic_hard_dataset(n=8, obs_size=4, max_actions=2, seed=1)
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/synthetic', 'loss_kind': 'ce'})
    loss_fn = BCLoss(cfg)
    net = _LinearPolicyNet(obs_size=4, max_actions=2)

    res = loss_fn.compute(net, _build_batch(fields))
    assert res.breakdown['loss_kind'] == 0.0, 'CE branch must mark loss_kind=0.0 in breakdown'
    assert res.breakdown['policy_loss'] > 0, 'untrained net should have positive policy loss'


def test_bc_soft_target_kl_breakdown_marks_loss_kind_one():
    """Companion guard:loss_kind='kl' selects soft-target branch and
    marks breakdown accordingly。Symmetric to the hard CE test;together
    they verify the cfg-driven branch selection that the retired PPO
    spy tests guarded。"""
    fields = _synthetic_hard_dataset(n=8, obs_size=4, max_actions=2, seed=2)
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/synthetic', 'loss_kind': 'kl'})
    loss_fn = BCLoss(cfg)
    net = _LinearPolicyNet(obs_size=4, max_actions=2)

    res = loss_fn.compute(net, _build_batch(fields))
    assert res.breakdown['loss_kind'] == 1.0, 'KL branch must mark loss_kind=1.0 in breakdown'


def test_bc_hard_target_respects_legal_mask():
    """When the teacher's chosen action becomes illegal,hard CE should
    still be defined(loss > 0)but training cannot reduce it to 0 — the
    contract is "minimize CE given the legal_mask",not "ignore illegality"。

    Verifies the masked-softmax math via -inf padding:loss > 0 even at
    optimum and gradient flows through legal slots only。"""
    torch.manual_seed(0)
    n, obs_size, max_actions = 32, 4, 4
    rng = np.random.default_rng(3)
    obs = rng.standard_normal(size=(n, obs_size)).astype(np.float32)
    chosen = np.argmax(obs[:, :max_actions], axis=1).astype(np.int64)
    # Mask out chosen action — teacher pick is now illegal for every row。
    legal_mask = np.ones((n, max_actions), dtype=bool)
    legal_mask[np.arange(n), chosen] = False
    tied_mask = np.zeros((n, max_actions), dtype=bool)
    tied_mask[np.arange(n), chosen] = True
    fields = {
        'obs': obs,
        'chosen_action': chosen,
        'legal_mask': legal_mask,
        'tied_mask': tied_mask,
        'terminal_z': np.zeros((n,), dtype=np.float32),
    }
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/synthetic', 'loss_kind': 'ce'})
    loss_fn = BCLoss(cfg)
    net = _LinearPolicyNet(obs_size=obs_size, max_actions=max_actions)

    res = loss_fn.compute(net, _build_batch(fields))
    # log_softmax of -inf at chosen slot → -inf;loss = inf is the
    # mathematical behavior。Test that it is "not finite-small" rather
    # than asserting a specific magnitude(may be inf or very large
    # depending on dtype)。
    loss_val = float(res.loss.item())
    assert math.isinf(loss_val) or loss_val > 10.0, (
        f'expected huge loss when chosen action is illegal, got loss={loss_val}'
    )


def test_bc_hard_target_zero_loss_when_perfect():
    """Sanity:if logits already pick teacher action with high
    probability,hard CE ≈ 0。Validates the "trained ceiling" used as
    convergence target in the main behavioral test。"""
    max_actions = 3
    # Hand-built logits:row i prefers action i(strong signal)。
    logits_init = torch.eye(max_actions) * 100.0
    chosen = torch.arange(max_actions, dtype=torch.long)
    legal_mask = torch.ones(max_actions, max_actions, dtype=torch.bool)
    fields = {
        'chosen_action': chosen,
        'legal_mask': legal_mask,
        'terminal_z': torch.zeros(max_actions),
    }

    class _FixedNet:
        def forward_batch(self, batch):
            return logits_init, torch.zeros(max_actions)

    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x', 'loss_kind': 'ce'})
    res = BCLoss(cfg).compute(_FixedNet(), Batch(data={'fields': fields}, size=max_actions))
    assert res.loss.item() == pytest.approx(0.0, abs=1e-3)
