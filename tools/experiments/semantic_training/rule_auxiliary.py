"""Train-only consequence head; gradients intentionally enter shared rule/action representations."""

import torch
from torch import nn

from tools.experiments.semantic_training.rule_outcomes import FIELDS, capture


class RuleHead(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(width * 2, width), nn.ReLU(), nn.Linear(width, len(FIELDS)))

    def forward(self, state, actions):
        return self.layers(torch.cat((state[:, None].expand_as(actions), actions), -1))


def attach(agent):
    agent.rule_head = RuleHead(agent.cfg.d_model).to(agent.device)
    return agent.rule_head


def labels(env, selected, rng, limit=8):
    groups = {}
    for i, label in enumerate(env.get_action_labels()):
        groups.setdefault(tuple(label), []).append(i)
    # Include executed action, then skills, then random remaining logical actions.
    # Independent Python RNG never consumes the policy's torch sampling stream.
    skills, other = [], []
    for label, indices in groups.items():
        if selected in indices:
            continue
        (skills if label[0] == 'Skill' else other).append(rng.choice(indices))
    rng.shuffle(skills)
    rng.shuffle(other)
    return capture(env, ([selected] + skills + other)[:limit])


def loss(head, state, actions, rows):
    predictions = head(state, actions)
    terms = []
    scale = predictions.new_tensor([10, 10, 3, 3, 1, 1, 1, 1, 1])
    for i, row in enumerate(rows):
        if 'rule_outcomes' not in row:
            continue
        data = row['rule_outcomes']
        if tuple(data['fields']) != FIELDS:
            raise ValueError('rule target schema mismatch')
        expected = predictions.new_tensor(data['targets']) / scale
        terms.append(nn.functional.smooth_l1_loss(predictions[i, data['actions']], expected))
    return torch.stack(terms).mean() if terms else predictions.sum() * 0
