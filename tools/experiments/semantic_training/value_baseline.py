"""Training-only state baseline; value gradients never alter the policy encoder."""

import torch
from torch import nn

from tools.experiments.semantic_training.agent import batch_observations


class StateValueHead(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(width, width), nn.Tanh(), nn.Linear(width, 1))
        nn.init.zeros_(self.layers[-1].weight)
        nn.init.zeros_(self.layers[-1].bias)

    def forward(self, state):
        return self.layers(state.detach()).squeeze(-1)


def attach(agent, weights=None):
    agent.value_head = StateValueHead(agent.cfg.d_model).to(agent.device)
    if weights is not None:
        agent.value_head.load_state_dict(weights)
    return agent.value_head


def predict(agent, obs):
    batch = batch_observations([obs], agent.cfg, agent.device)
    batch['hook_emb'] = agent._hook_emb
    with torch.no_grad():
        logits, state = agent.net(batch, return_state=True)
        logits = logits[0, : obs['n_legal']]
        value = agent.value_head(state)[0]
    if not torch.isfinite(logits).all() or not torch.isfinite(value):
        raise ValueError('nonfinite state-baseline prediction')
    return logits, float(value)


def advantages(rewards, old_values):
    # Gamma=lambda=1 and a true terminal outcome: G_t is the terminal reward.
    # Baselines are frozen at collection, including across internal reroll decisions.
    return (rewards - old_values).detach()
