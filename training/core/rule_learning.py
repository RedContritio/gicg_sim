"""Supervised rule-cost probe and explicit old/new replay sampling.

Targets must come from the engine before the selected action executes. This
auxiliary task measures immediate rule understanding, not playing strength.
"""

import numpy as np
import torch
from torch import nn

from training.core.obs_constants import ACTION_REROLL


class RuleCostProbe(nn.Module):
    """Uses the SAME encoder objects as a policy, so gradients transfer directly."""

    def __init__(self, hook_encoder, buff_encoder, d_model):
        super().__init__()
        self.hook_encoder = hook_encoder
        self.buff_encoder = buff_encoder
        self.query = nn.Linear(2, d_model)
        self.head = nn.Sequential(nn.Linear(d_model * 2, d_model), nn.ReLU(), nn.Linear(d_model, 1))

    def forward(self, hook_ir, hook_mask, buffs, action_refs):
        hooks = self.hook_encoder(hook_ir, hook_mask)
        refs = action_refs[:, 1].long()
        valid = (refs >= 0) & (action_refs[:, 0] != ACTION_REROLL)
        if (refs[valid] >= hooks.shape[1]).any():
            raise ValueError('action refers to missing rule')
        indices = torch.where(valid, refs, 0)
        action = hooks[torch.arange(len(hooks), device=hooks.device), indices] * valid.unsqueeze(-1)
        action = action + self.query(action_refs[:, [0, 2]].float())
        instances = self.buff_encoder(buffs, hooks)
        return self.head(torch.cat((action, instances), dim=-1)).squeeze(-1)


def mixed_indices(old_size, new_size, batch_size, new_fraction, rng):
    """Return (source, index) pairs; each nonzero fraction requires that source."""
    if not 0 <= new_fraction <= 1 or batch_size <= 0:
        raise ValueError('invalid adaptation batch configuration')
    n_new = round(batch_size * new_fraction)
    n_old = batch_size - n_new
    if (n_new and new_size <= 0) or (n_old and old_size <= 0):
        raise ValueError('requested replay source is empty')
    pairs = [(0, int(i)) for i in rng.integers(old_size, size=n_old)] if n_old else []
    if n_new:
        pairs += [(1, int(i)) for i in rng.integers(new_size, size=n_new)]
    rng.shuffle(pairs)
    return pairs


def split_rule_groups(groups, held_out):
    """Hold out WHOLE rule combinations, never random steps from the same game."""
    groups = np.asarray(groups)
    mask = np.isin(groups, list(held_out))
    train, test = np.flatnonzero(~mask), np.flatnonzero(mask)
    if not len(train) or not len(test):
        raise ValueError('need both training and held-out rule groups')
    return train, test
