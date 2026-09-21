from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from training.core.obs_constants import ACTION_REROLL
from training.core.protocols import Batch
from training.paradigms.az.loss import AZLoss


class _Network:
    def __init__(self, logits: torch.Tensor):
        self.logits = logits
        self.net = torch.nn.Linear(1, 1)

    def forward_batch(self, batch):
        size = self.logits.shape[0]
        return self.logits, torch.zeros(size), torch.zeros(size, 1)


def _loss(exclude_reroll: bool, current_logits: torch.Tensor, reference_logits: torch.Tensor) -> AZLoss:
    train = SimpleNamespace(
        l2_coef=0.0,
        entropy_coef=0.0,
        delta_aux_coef=0.0,
        anchor_beta=1.0,
        anchor_exclude_reroll=exclude_reroll,
    )
    loss = AZLoss(SimpleNamespace(train=train))
    loss._anchor_ref_net = _Network(reference_logits)
    return loss


def _batch(kinds: torch.Tensor) -> Batch:
    batch_size, action_count = kinds.shape
    action_refs = torch.zeros(batch_size, action_count, 3, dtype=torch.int64)
    action_refs[..., 0] = kinds
    return Batch(
        data={
            'pi_target': torch.full((batch_size, action_count), 1.0 / action_count),
            'z_target': torch.zeros(batch_size),
            'legal_mask': torch.ones(batch_size, action_count, dtype=torch.bool),
            'action_refs': action_refs,
        },
        size=batch_size,
    )


def test_anchor_can_exclude_reroll_decision_rows():
    current = torch.tensor([[8.0, -8.0], [-8.0, 8.0]])
    reference = torch.tensor([[8.0, -8.0], [8.0, -8.0]])
    kinds = torch.tensor([[0, 0], [ACTION_REROLL, ACTION_REROLL]])

    included = _loss(False, current, reference).compute(_Network(current), _batch(kinds))
    excluded = _loss(True, current, reference).compute(_Network(current), _batch(kinds))

    assert included.breakdown['anchor'] > 7.0
    assert excluded.breakdown['anchor'] < 1e-5


def test_anchor_is_zero_when_batch_contains_only_reroll_rows():
    current = torch.tensor([[-8.0, 8.0]], requires_grad=True)
    reference = torch.tensor([[8.0, -8.0]])
    kinds = torch.tensor([[ACTION_REROLL, ACTION_REROLL]])

    result = _loss(True, current, reference).compute(_Network(current), _batch(kinds))

    assert result.breakdown['anchor'] == pytest.approx(0.0)
    assert torch.isfinite(result.loss)
    result.loss.backward()
