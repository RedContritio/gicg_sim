from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import Tensor, nn

from .config import TrainingConfig

CHECKPOINT_VERSION = 5


class DmcQNetwork(nn.Module):
    def __init__(self, state_size: int, action_size: int, hidden_size: int):
        super().__init__()
        self.state_encoder = nn.Sequential(
            nn.Linear(state_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.action_encoder = nn.Sequential(
            nn.Linear(action_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.q = nn.Sequential(
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, states: Tensor, actions: Tensor) -> Tensor:
        state_features = self.state_encoder(states)
        action_features = self.action_encoder(actions)
        if state_features.ndim == 1 and action_features.ndim == 2:
            state_features = state_features.expand(action_features.shape[0], -1)
        return self.q(torch.cat((state_features, action_features), dim=-1)).squeeze(-1)


@dataclass(frozen=True)
class Transition:
    state: np.ndarray
    action: np.ndarray


class ReplayBuffer:
    def __init__(
        self,
        capacity: int,
        state_size: int,
        action_size: int,
        seed: int,
        device: torch.device,
    ):
        self.capacity = capacity
        self.device = device
        self.states = torch.empty((capacity, state_size), dtype=torch.float32, device=device)
        self.actions = torch.empty((capacity, action_size), dtype=torch.float32, device=device)
        self.returns = torch.empty(capacity, dtype=torch.float32, device=device)
        self.size = 0
        self.next = 0
        self.total_seen = 0
        self.random = torch.Generator(device=device).manual_seed(seed)

    def __len__(self) -> int:
        return self.size

    def push_episode(self, transitions: list[Transition], outcome: float) -> None:
        count = len(transitions)
        if count == 0:
            return
        if count > self.capacity:
            raise RuntimeError("episode exceeds replay capacity")
        indices = (torch.arange(count, device=self.device) + self.next) % self.capacity
        states = torch.from_numpy(np.stack([item.state for item in transitions])).to(self.device)
        actions = torch.from_numpy(np.stack([item.action for item in transitions])).to(self.device)
        self.states.index_copy_(0, indices, states)
        self.actions.index_copy_(0, indices, actions)
        self.returns.index_fill_(0, indices, outcome)
        self.next = (self.next + count) % self.capacity
        self.size = min(self.size + count, self.capacity)
        self.total_seen += count

    def sample(self, count: int) -> tuple[Tensor, Tensor, Tensor]:
        indices = torch.randint(self.size, (count,), generator=self.random, device=self.device)
        return self.states[indices], self.actions[indices], self.returns[indices]

    def state_dict(self) -> dict:
        return {
            "states": self.states[: self.size].cpu(),
            "actions": self.actions[: self.size].cpu(),
            "returns": self.returns[: self.size].cpu(),
            "random": self.random.get_state(),
            "total_seen": self.total_seen,
            "next": self.next,
        }

    def load_state_dict(self, state: dict) -> None:
        size = int(state["returns"].shape[0])
        if size > self.capacity:
            raise RuntimeError("checkpoint replay exceeds configured capacity")
        if state["states"].shape[1:] != self.states.shape[1:]:
            raise RuntimeError("checkpoint replay state shape does not match the environment")
        if state["actions"].shape[1:] != self.actions.shape[1:]:
            raise RuntimeError("checkpoint replay action shape does not match the environment")
        self.states[:size].copy_(state["states"].to(self.device))
        self.actions[:size].copy_(state["actions"].to(self.device))
        self.returns[:size].copy_(state["returns"].to(self.device))
        self.size = size
        self.next = int(state["next"])
        self.total_seen = int(state["total_seen"])
        self.random.set_state(state["random"])


class DmcAlgorithm:
    def __init__(self, state_size: int, action_size: int, config: TrainingConfig, seed: int):
        self.config = config
        self.device = torch.device(config.device)
        self.state_size = state_size
        self.action_size = action_size
        self.model = DmcQNetwork(state_size, action_size, config.hidden_size).to(self.device)
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        self.replay = ReplayBuffer(
            config.replay_capacity, state_size, action_size, seed, self.device
        )
        self.updates = 0

    def select(
        self,
        observation: dict[str, np.ndarray],
        epsilon: float,
        random: np.random.Generator,
    ) -> tuple[int, Transition]:
        return select_action(self.model, self.device, observation, epsilon, random)

    def actor_state(self) -> dict[str, np.ndarray]:
        return {
            name: value.detach().cpu().numpy().copy()
            for name, value in self.model.state_dict().items()
        }

    def learn_episode(self, transitions: list[Transition], outcome: float) -> dict[str, float]:
        self.replay.push_episode(transitions, outcome)
        losses = []
        q_means = []
        target_means = []
        for _ in range(self.config.updates_per_episode):
            if len(self.replay) < self.config.batch_size:
                break
            loss, q_mean, target_mean = self._update()
            losses.append(loss)
            q_means.append(q_mean)
            target_means.append(target_mean)
        return {
            "loss": float(np.mean(losses)) if losses else 0.0,
            "q_mean": float(np.mean(q_means)) if q_means else 0.0,
            "target_mean": float(np.mean(target_means)) if target_means else 0.0,
            "updates": len(losses),
            "replay_size": len(self.replay),
            "transitions": len(transitions),
        }

    def _update(self) -> tuple[float, float, float]:
        states, actions, returns = self.replay.sample(self.config.batch_size)
        predicted = self.model(states, actions)
        loss = nn.functional.mse_loss(predicted, returns)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_grad_norm)
        self.optimizer.step()
        self.updates += 1
        return loss.item(), predicted.detach().mean().item(), returns.mean().item()

    def checkpoint(self, path: Path, episode: int, ruleset: str) -> None:
        torch.save(
            {
                "format": CHECKPOINT_VERSION,
                "algorithm": "dmc",
                "episode": episode,
                "updates": self.updates,
                "ruleset": ruleset,
                "state_size": self.state_size,
                "action_size": self.action_size,
                "hidden_size": self.config.hidden_size,
                "training": training_signature(self.config),
                "model": self.model.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "replay": self.replay.state_dict(),
                "torch_rng": torch.get_rng_state(),
                "device_type": self.device.type,
                "device_rng": get_device_rng(self.device),
            },
            path,
        )

    def restore(self, path: Path, ruleset: str) -> int:
        checkpoint = load_checkpoint(path)
        validate_checkpoint(
            checkpoint,
            ruleset,
            self.state_size,
            self.action_size,
            self.config.hidden_size,
        )
        if checkpoint["training"] != training_signature(self.config):
            raise RuntimeError("checkpoint training configuration does not match")
        if checkpoint["device_type"] != self.device.type:
            raise RuntimeError(
                f"training resume requires device {checkpoint['device_type']!r}, "
                f"got {self.device.type!r}"
            )
        self.model.load_state_dict(checkpoint["model"], strict=True)
        self.optimizer.load_state_dict(checkpoint["optimizer"])
        self.replay.load_state_dict(checkpoint["replay"])
        self.updates = int(checkpoint["updates"])
        torch.set_rng_state(checkpoint["torch_rng"].cpu())
        set_device_rng(self.device, checkpoint["device_rng"])
        return int(checkpoint["episode"])


def exploration(config: TrainingConfig, episode: int) -> float:
    progress = min(episode / config.epsilon_decay_episodes, 1.0)
    return config.epsilon_start + progress * (config.epsilon_end - config.epsilon_start)


def select_action(
    model: DmcQNetwork,
    device: torch.device,
    observation: dict[str, np.ndarray],
    epsilon: float,
    random: np.random.Generator,
) -> tuple[int, Transition]:
    count = int(observation["action_mask"].sum())
    if count == 0:
        raise RuntimeError("policy received no legal actions")
    if random.random() < epsilon:
        selected = int(random.integers(count))
    else:
        state = torch.as_tensor(observation["state"], device=device)
        actions = torch.as_tensor(observation["actions"][:count], device=device)
        with torch.no_grad():
            selected = int(model(state, actions).argmax().item())
    return selected, Transition(
        state=observation["state"].copy(),
        action=observation["actions"][selected].copy(),
    )


def training_signature(config: TrainingConfig) -> dict:
    return {
        "actors": config.actors,
        "rollout_batch_size": config.rollout_batch_size,
        "batch_size": config.batch_size,
        "replay_capacity": config.replay_capacity,
        "updates_per_episode": config.updates_per_episode,
        "epsilon_start": config.epsilon_start,
        "epsilon_end": config.epsilon_end,
        "epsilon_decay_episodes": config.epsilon_decay_episodes,
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "max_grad_norm": config.max_grad_norm,
        "random_opponent_weight": config.random_opponent_weight,
        "f1d2_opponent_weight": config.f1d2_opponent_weight,
        "opponent_node_budget": config.opponent_node_budget,
    }


def load_policy(
    path: Path,
    ruleset: str,
    state_size: int,
    action_size: int,
    device: str,
) -> DmcQNetwork:
    target = torch.device(device)
    checkpoint = load_checkpoint(path)
    hidden_size = int(checkpoint["hidden_size"])
    validate_checkpoint(checkpoint, ruleset, state_size, action_size, hidden_size)
    model = DmcQNetwork(state_size, action_size, hidden_size).to(target)
    model.load_state_dict(checkpoint["model"], strict=True)
    model.eval()
    return model


def load_checkpoint(path: Path) -> dict:
    return torch.load(path, map_location="cpu", weights_only=True)


def validate_checkpoint(
    checkpoint: dict,
    ruleset: str,
    state_size: int,
    action_size: int,
    hidden_size: int,
) -> None:
    expected = {
        "format": CHECKPOINT_VERSION,
        "algorithm": "dmc",
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
