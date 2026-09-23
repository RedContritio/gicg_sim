import tomllib
from dataclasses import dataclass
from pathlib import Path


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
    hidden_size: int
    learning_rate: float
    entropy_weight: float
    value_weight: float
    checkpoint_every: int
    device: str


@dataclass(frozen=True)
class EvaluationConfig:
    episodes: int
    seed: int
    candidate: str
    opponent: str
    node_budget: int
    device: str


def load_environment_config(path: Path) -> EnvironmentConfig:
    with path.open("rb") as file:
        raw = tomllib.load(file)
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


def load_training_config(path: Path) -> TrainingConfig:
    with path.open("rb") as file:
        raw = tomllib.load(file)["training"]
    return TrainingConfig(
        experiment_tag=raw["experiment_tag"],
        episodes=raw["episodes"],
        hidden_size=raw["hidden_size"],
        learning_rate=raw["learning_rate"],
        entropy_weight=raw["entropy_weight"],
        value_weight=raw["value_weight"],
        checkpoint_every=raw["checkpoint_every"],
        device=raw["device"],
    )


def load_evaluation_config(path: Path) -> EvaluationConfig:
    with path.open("rb") as file:
        raw = tomllib.load(file)["evaluation"]
    return EvaluationConfig(
        episodes=raw["episodes"],
        seed=raw["seed"],
        candidate=raw["candidate"],
        opponent=raw["opponent"],
        node_budget=raw["node_budget"],
        device=raw["device"],
    )
