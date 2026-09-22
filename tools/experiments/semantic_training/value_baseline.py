"""Training-only state baseline; value gradients never alter the policy encoder."""

import torch
from torch import nn

from tools.experiments.semantic_training.agent import batch_observations

SIGNED_OUTCOME = 'signed_outcome'
EXPECTED_SCORE = 'expected_score'
WIN_PROBABILITY = 'win_probability'
VALUE_ENCODINGS = (SIGNED_OUTCOME, EXPECTED_SCORE, WIN_PROBABILITY)


def validate_value_encoding(value):
    if value not in VALUE_ENCODINGS:
        raise ValueError(f'unknown value encoding {value!r}')
    return value


def convert_value_head_state(state, source, target):
    validate_value_encoding(source)
    validate_value_encoding(target)
    converted = {key: value.clone() for key, value in state.items()}
    score_encodings = {EXPECTED_SCORE, WIN_PROBABILITY}
    if source == target or source in score_encodings and target in score_encodings:
        return converted
    weight_key, bias_key = 'layers.2.weight', 'layers.2.bias'
    if weight_key not in converted or bias_key not in converted:
        raise ValueError('value head is missing its final affine layer')
    if source in score_encodings and target == SIGNED_OUTCOME:
        converted[weight_key] *= 2
        converted[bias_key] = converted[bias_key] * 2 - 1
    else:
        converted[weight_key] *= 0.5
        converted[bias_key] = (converted[bias_key] + 1) * 0.5
    return converted


def signed_value_head_state(payload):
    state = payload.get('value_head')
    if state is None:
        return None
    return convert_value_head_state(state, payload.get('value_encoding', SIGNED_OUTCOME), SIGNED_OUTCOME)


def signed_to_expected_score(value):
    return (float(value) + 1.0) * 0.5


signed_to_probability = signed_to_expected_score


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


def make_optimizer(agent, weights=None, lr=0.0003):
    return torch.optim.AdamW(attach(agent, weights).parameters(), lr=lr, weight_decay=0)


def predict(agent, obs):
    batch = batch_observations([obs], agent.cfg, agent.device)
    batch['hook_emb'] = agent._hook_emb
    with torch.no_grad():
        logits, state = agent.net(batch, return_state=True)
        logits = logits[0, : obs['n_legal']]
        value = agent.value_head(state)[0]
        if getattr(agent, 'value_encoding', SIGNED_OUTCOME) in {EXPECTED_SCORE, WIN_PROBABILITY}:
            value = value * 2 - 1
    if not torch.isfinite(logits).all() or not torch.isfinite(value):
        raise ValueError('nonfinite state-baseline prediction')
    return logits, float(value)


def advantages(rewards, old_values):
    # Gamma=lambda=1 and a true terminal outcome: G_t is the terminal reward.
    # Baselines are frozen at collection, including across internal reroll decisions.
    return (rewards - old_values).detach()
