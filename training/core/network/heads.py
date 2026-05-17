"""Paradigm-agnostic head modules.

ParadigmAgnostic head set — paradigm picks the subset it needs in its
own ActorCritic composition (paradigms/<name>/network.py).

| Head | Used by |
|---|---|
| PolicyHead | AZ / PPO / BC (policy logits) |
| ValueHead | AZ / PPO / DMC value baseline |
| QHead | DMC (logit-as-Q — review B.1) |
| AvgPolicyHead | CFR (average strategy) |
| DeltaHead | AZ (counter delta MCTS bootstrap) |
"""

from __future__ import annotations

import torch
import torch.nn as nn


class PolicyHead(nn.Module):
    """Action-embedding-dotted policy logits.
    state_vec (B, d) ⊕ action_emb (B, N, d) → logits (B, N)."""

    def __init__(self, d_model: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.state_proj = nn.Sequential(
            nn.Linear(d_model, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, d_model),
        )

    def forward(self, state_vec: torch.Tensor, action_emb: torch.Tensor) -> torch.Tensor:
        s = self.state_proj(state_vec)
        return (s.unsqueeze(1) * action_emb).sum(-1)


class ValueHead(nn.Module):
    """Scalar value V(s) ∈ [-1, 1] via tanh."""

    def __init__(self, in_dim: int, d_model: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.head = nn.Sequential(
            nn.Linear(in_dim, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.tanh(self.head(x).squeeze(-1))


class QHead(nn.Module):
    """DMC review B.1 'logit-as-Q' head — outputs unnormalized Q values
    per action. Same MLP shape as PolicyHead but the loss treats output
    as Q (MSE vs Monte Carlo return) not policy logits."""

    def __init__(self, d_model: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.state_proj = nn.Sequential(
            nn.Linear(d_model, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, d_model),
        )

    def forward(self, state_vec: torch.Tensor, action_emb: torch.Tensor) -> torch.Tensor:
        s = self.state_proj(state_vec)
        return (s.unsqueeze(1) * action_emb).sum(-1)


class AvgPolicyHead(nn.Module):
    """CFR average policy head — same shape as PolicyHead but trained
    against reservoir-weighted strategy targets."""

    def __init__(self, d_model: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.state_proj = nn.Sequential(
            nn.Linear(d_model, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, d_model),
        )

    def forward(self, state_vec: torch.Tensor, action_emb: torch.Tensor) -> torch.Tensor:
        s = self.state_proj(state_vec)
        return (s.unsqueeze(1) * action_emb).sum(-1)


class DeltaHead(nn.Module):
    """AZ counter-delta prediction head. Output: (B, n_counter_slots)."""

    def __init__(self, in_dim: int, d_model: int, n_counter_slots: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.head = nn.Sequential(
            nn.Linear(in_dim, d_model * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, n_counter_slots),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)
