"""Policy residual over frozen semantic representations and predicted consequences.

The paired control has identical trainable capacity but receives zero consequence
features. Both arms start with exactly the supplied backbone's action scores.
"""

import torch
from torch import nn

from tools.experiments.semantic_training.rule_outcomes import FIELDS


FORMAT = 'consequence-policy/1.0.0'


class ConsequencePolicyNet(nn.Module):
    def __init__(self, backbone, rule_head, width, *, use_consequences=True):
        super().__init__()
        self.backbone = backbone.requires_grad_(False)
        self.rule_head = rule_head.requires_grad_(False)
        self.use_consequences = use_consequences
        self.residual = nn.Sequential(
            nn.Linear(2 * width + len(FIELDS), width), nn.Tanh(), nn.Linear(width, 1, bias=False)
        )
        nn.init.zeros_(self.residual[-1].weight)
        self.train(False)

    @property
    def hook_encoder(self):
        return self.backbone.hook_encoder

    def train(self, mode=True):
        super().train(mode)
        # Dropout and cached hook embeddings must agree between sampling and updates.
        self.backbone.eval()
        self.rule_head.eval()
        return self

    def forward(self, batch, *, return_state=False, return_actions=False):
        with torch.no_grad():
            logits, state, actions = self.backbone(batch, return_actions=True)
            outcomes = self.rule_head(state, actions)
            if not self.use_consequences:
                outcomes = torch.zeros_like(outcomes)
        context = torch.cat((state[:, None].expand_as(actions), actions, outcomes), -1)
        logits = logits + self.residual(context).squeeze(-1)
        if return_actions:
            return logits, state, actions
        return (logits, state) if return_state else logits
