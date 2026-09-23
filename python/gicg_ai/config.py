import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MatchConfig:
    ruleset: Path
    players: tuple[list[str], list[str]]
    decks: tuple[list[str], list[str]]
    format: tuple[int, int, int]
    first: int


@dataclass(frozen=True)
class EnvironmentConfig:
    match: MatchConfig
    seed: int
    max_actions: int
    max_steps: int


@dataclass(frozen=True)
class TrainingConfig:
    experiment_tag: str
    episodes: int
    actors: int
    rollout_batch_size: int
    hidden_size: int
    learning_rate: float
    weight_decay: float
    batch_size: int
    replay_capacity: int
    updates_per_episode: int
    epsilon_start: float
    epsilon_end: float
    epsilon_decay_episodes: int
    max_grad_norm: float
    random_opponent_weight: float
    f1d2_opponent_weight: float
    opponent_node_budget: int
    checkpoint_every: int
    keep_checkpoints: int
    device: str


@dataclass(frozen=True)
class EvaluationConfig:
    episodes: int
    seed: int
    candidate: str
    opponent: str
    node_budget: int
    device: str


def load_environment_config(path: Path, overrides: tuple[str, ...] = ()) -> EnvironmentConfig:
    raw = load_config(path, overrides)
    game = raw["game"]
    environment = raw["environment"]
    match = MatchConfig(
        ruleset=(Path.cwd() / game["ruleset"]).resolve(),
        players=(game["player_one"], game["player_two"]),
        decks=(game["player_one_deck"], game["player_two_deck"]),
        format=(game["team_size"], game["deck_size"], game["max_card_copies"]),
        first=game["first"],
    )
    return EnvironmentConfig(
        match=match,
        seed=environment["seed"],
        max_actions=environment["max_actions"],
        max_steps=environment["max_steps"],
    )


def load_training_config(path: Path, overrides: tuple[str, ...] = ()) -> TrainingConfig:
    raw = load_config(path, overrides)["training"]
    return TrainingConfig(
        experiment_tag=raw["experiment_tag"],
        episodes=raw["episodes"],
        actors=raw["actors"],
        rollout_batch_size=raw["rollout_batch_size"],
        hidden_size=raw["hidden_size"],
        learning_rate=raw["learning_rate"],
        weight_decay=raw["weight_decay"],
        batch_size=raw["batch_size"],
        replay_capacity=raw["replay_capacity"],
        updates_per_episode=raw["updates_per_episode"],
        epsilon_start=raw["epsilon_start"],
        epsilon_end=raw["epsilon_end"],
        epsilon_decay_episodes=raw["epsilon_decay_episodes"],
        max_grad_norm=raw["max_grad_norm"],
        random_opponent_weight=raw["random_opponent_weight"],
        f1d2_opponent_weight=raw["f1d2_opponent_weight"],
        opponent_node_budget=raw["opponent_node_budget"],
        checkpoint_every=raw["checkpoint_every"],
        keep_checkpoints=raw["keep_checkpoints"],
        device=raw["device"],
    )


def load_evaluation_config(path: Path, overrides: tuple[str, ...] = ()) -> EvaluationConfig:
    raw = load_config(path, overrides)["evaluation"]
    return EvaluationConfig(
        episodes=raw["episodes"],
        seed=raw["seed"],
        candidate=raw["candidate"],
        opponent=raw["opponent"],
        node_budget=raw["node_budget"],
        device=raw["device"],
    )


def load_config(path: Path, overrides: tuple[str, ...] = ()) -> dict[str, Any]:
    with path.open("rb") as file:
        config = tomllib.load(file)
    for override in overrides:
        apply_override(config, override)
    return config


def apply_override(config: dict[str, Any], override: str) -> None:
    path, separator, raw_value = override.partition("=")
    if not separator or not path or not raw_value:
        raise RuntimeError(f"invalid config override {override!r}")
    keys = path.split(".")
    target = config
    for key in keys[:-1]:
        value = target.get(key)
        if not isinstance(value, dict):
            raise RuntimeError(f"unknown config path {path!r}")
        target = value
    key = keys[-1]
    if key not in target:
        raise RuntimeError(f"unknown config path {path!r}")
    target[key] = parse_override_value(raw_value)


def parse_override_value(value: str) -> Any:
    try:
        return tomllib.loads(f"value = {value}")["value"]
    except tomllib.TOMLDecodeError:
        return value
