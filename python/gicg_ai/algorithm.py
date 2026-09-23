from dataclasses import dataclass
from math import sqrt

import numpy as np
import torch
from torch import Tensor, nn
from torch.distributions import Categorical

from .config import TrainingConfig


class CandidateActorCritic(nn.Module):
    def __init__(self, state_size: int, action_size: int, hidden_size: int):
        super().__init__()
        self.state_encoder = nn.Sequential(
            nn.Linear(state_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.action_encoder = nn.Sequential(
            nn.Linear(action_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.value = nn.Linear(hidden_size, 1)
        self.scale = sqrt(hidden_size)

    def forward(self, state: Tensor, actions: Tensor) -> tuple[Tensor, Tensor]:
        context = self.state_encoder(state)
        candidates = self.action_encoder(actions)
        logits = candidates @ context / self.scale
        return logits, self.value(context).squeeze(-1)


@dataclass
class Decision:
    log_probability: Tensor
    entropy: Tensor
    value: Tensor


class EpisodicActorCritic:
    def __init__(
        self,
        state_size: int,
        action_size: int,
        config: TrainingConfig,
    ):
        self.config = config
        self.device = torch.device(config.device)
        self.model = CandidateActorCritic(state_size, action_size, config.hidden_size).to(
            self.device
        )
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=config.learning_rate)

    def select(self, observation: dict[str, np.ndarray]) -> tuple[int, Decision]:
        count = int(observation["action_mask"].sum())
        if count == 0:
            raise RuntimeError("policy received no legal actions")
        state = torch.as_tensor(observation["state"], device=self.device)
        actions = torch.as_tensor(observation["actions"][:count], device=self.device)
        logits, value = self.model(state, actions)
        distribution = Categorical(logits=logits)
        action = distribution.sample()
        decision = Decision(distribution.log_prob(action), distribution.entropy(), value)
        return int(action.item()), decision

    def update(self, trajectories: list[list[Decision]], winner: int) -> dict[str, float]:
        policy_losses = []
        value_losses = []
        entropies = []
        for player, decisions in enumerate(trajectories):
            outcome = torch.tensor(1.0 if player == winner else -1.0, device=self.device)
            for decision in decisions:
                advantage = outcome - decision.value.detach()
                policy_losses.append(-decision.log_probability * advantage)
                value_losses.append((decision.value - outcome).square())
                entropies.append(decision.entropy)
        policy_loss = torch.stack(policy_losses).mean()
        value_loss = torch.stack(value_losses).mean()
        entropy = torch.stack(entropies).mean()
        loss = (
            policy_loss
            + self.config.value_weight * value_loss
            - self.config.entropy_weight * entropy
        )
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        return {
            "loss": loss.item(),
            "policy_loss": policy_loss.item(),
            "value_loss": value_loss.item(),
            "entropy": entropy.item(),
        }

    def checkpoint(self, path, episode: int) -> None:
        torch.save(
            {
                "episode": episode,
                "model": self.model.state_dict(),
                "optimizer": self.optimizer.state_dict(),
            },
            path,
        )
