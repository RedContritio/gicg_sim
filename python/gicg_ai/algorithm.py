from dataclasses import dataclass
from math import sqrt
from pathlib import Path

import numpy as np
import torch
from torch import Tensor, nn
from torch.distributions import Categorical

from .config import TrainingConfig

CHECKPOINT_VERSION = 1


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
        self.state_size = state_size
        self.action_size = action_size
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

    def checkpoint(self, path: Path, episode: int, ruleset: str) -> None:
        torch.save(
            {
                "format": CHECKPOINT_VERSION,
                "episode": episode,
                "ruleset": ruleset,
                "state_size": self.state_size,
                "action_size": self.action_size,
                "hidden_size": self.config.hidden_size,
                "device_type": self.device.type,
                "model": self.model.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "torch_rng": torch.get_rng_state(),
                "device_rng": get_device_rng(self.device),
            },
            path,
        )

    def restore(self, path: Path, ruleset: str) -> int:
        checkpoint = load_checkpoint(path, self.device)
        validate_checkpoint(
            checkpoint,
            ruleset,
            self.state_size,
            self.action_size,
            self.config.hidden_size,
        )
        self.model.load_state_dict(checkpoint["model"], strict=True)
        self.optimizer.load_state_dict(checkpoint["optimizer"])
        if checkpoint["device_type"] != self.device.type:
            raise RuntimeError(
                f"training resume requires device {checkpoint['device_type']!r}, "
                f"got {self.device.type!r}"
            )
        torch.set_rng_state(checkpoint["torch_rng"].cpu())
        set_device_rng(self.device, checkpoint["device_rng"])
        return int(checkpoint["episode"])


def load_policy(
    path: Path,
    ruleset: str,
    state_size: int,
    action_size: int,
    device: str,
) -> CandidateActorCritic:
    target = torch.device(device)
    checkpoint = load_checkpoint(path, target)
    hidden_size = int(checkpoint["hidden_size"])
    validate_checkpoint(checkpoint, ruleset, state_size, action_size, hidden_size)
    model = CandidateActorCritic(state_size, action_size, hidden_size).to(target)
    model.load_state_dict(checkpoint["model"], strict=True)
    model.eval()
    return model


def load_checkpoint(path: Path, device: torch.device) -> dict:
    return torch.load(path, map_location=device, weights_only=True)


def validate_checkpoint(
    checkpoint: dict,
    ruleset: str,
    state_size: int,
    action_size: int,
    hidden_size: int,
) -> None:
    expected = {
        "format": CHECKPOINT_VERSION,
        "ruleset": ruleset,
        "state_size": state_size,
        "action_size": action_size,
        "hidden_size": hidden_size,
    }
    actual = {key: checkpoint.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(f"checkpoint protocol mismatch: expected {expected}, got {actual}")


def get_device_rng(device: torch.device) -> Tensor | None:
    if device.type == "cuda":
        return torch.cuda.get_rng_state(device)
    if device.type == "mps":
        return torch.mps.get_rng_state()
    return None


def set_device_rng(device: torch.device, state: Tensor | None) -> None:
    if device.type == "cuda":
        torch.cuda.set_rng_state(state, device)
    elif device.type == "mps":
        torch.mps.set_rng_state(state)
