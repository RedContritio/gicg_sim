import argparse
import json
import re
from pathlib import Path
from typing import Protocol

import numpy as np
import torch

from .algorithm import DmcQNetwork, load_policy
from .config import EvaluationConfig, load_environment_config, load_evaluation_config
from .env import GicgEnv, env


class Policy(Protocol):
    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int: ...


class RandomPolicy:
    def __init__(self, random: np.random.Generator):
        self.random = random

    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int:
        del observation
        return int(self.random.integers(len(game.legal_actions)))


class GreedyPolicy:
    def __init__(
        self,
        features: int,
        depth: int,
        node_budget: int,
        random: np.random.Generator,
    ):
        self.features = features
        self.depth = depth
        self.node_budget = node_budget
        self.random = random

    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int:
        del observation
        seed = int(self.random.integers(0, np.iinfo(np.uint64).max, dtype=np.uint64))
        return game.select_greedy_action(
            self.features,
            self.depth,
            self.node_budget,
            seed,
        )


class CheckpointPolicy:
    def __init__(self, model: DmcQNetwork, device: str):
        self.model = model
        self.device = torch.device(device)

    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int:
        del game
        count = int(observation["action_mask"].sum())
        state = torch.as_tensor(observation["state"], device=self.device)
        actions = torch.as_tensor(observation["actions"][:count], device=self.device)
        with torch.no_grad():
            q_values = self.model(state, actions)
        return int(q_values.argmax().item())


def evaluate(
    config_path: Path,
    candidate_checkpoint: Path | None = None,
    opponent_checkpoint: Path | None = None,
) -> dict:
    environment_config = load_environment_config(config_path)
    evaluation_config = load_evaluation_config(config_path)
    if evaluation_config.episodes < 1:
        raise RuntimeError("evaluation episodes must be positive")
    game = env(environment_config)
    random = np.random.default_rng(evaluation_config.seed)
    candidate = create_policy(
        evaluation_config.candidate,
        candidate_checkpoint,
        game,
        evaluation_config.device,
        random,
        evaluation_config.node_budget,
    )
    opponent = create_policy(
        evaluation_config.opponent,
        opponent_checkpoint,
        game,
        evaluation_config.device,
        random,
        evaluation_config.node_budget,
    )
    games = []
    for episode in range(evaluation_config.episodes):
        seed = evaluation_config.seed + episode
        games.append(play_game(game, [candidate, opponent], seed, 0))
        games.append(play_game(game, [opponent, candidate], seed, 1))
    game.close()
    return summarize(games, evaluation_config, candidate_checkpoint, opponent_checkpoint)


def create_policy(
    name: str,
    checkpoint: Path | None,
    game: GicgEnv,
    device: str,
    random: np.random.Generator,
    node_budget: int,
) -> Policy:
    if checkpoint is not None:
        model = load_policy(
            checkpoint,
            game.rules["hash"],
            game.state_encoder.size,
            game.action_encoder.size,
            device,
        )
        return CheckpointPolicy(model, device)
    if name == "random":
        return RandomPolicy(random)
    match = re.fullmatch(r"F([1-5])D([1-9][0-9]*)", name)
    if match:
        return GreedyPolicy(int(match[1]), int(match[2]), node_budget, random)
    raise RuntimeError(f"unknown policy {name!r}")


def play_game(game: GicgEnv, policies: list[Policy], seed: int, candidate_seat: int) -> dict:
    game.reset(seed=seed)
    while game.state["phase"] != "finished":
        observation, _, terminated, truncated, _ = game.last()
        if terminated:
            break
        if truncated:
            break
        player = game.agent_name_mapping[game.agent_selection]
        game.step(policies[player].select(observation, game))
    return {
        "seed": seed,
        "candidate_seat": candidate_seat,
        "winner": game.state["winner"],
        "candidate_won": game.state["winner"] == candidate_seat,
        "draw": game.state["winner"] is None,
        "steps": game.steps,
        "rounds": game.state["round"],
    }


def summarize(
    games: list[dict],
    config: EvaluationConfig,
    candidate_checkpoint: Path | None,
    opponent_checkpoint: Path | None,
) -> dict:
    wins, draws, losses = outcome_counts(games)
    return {
        "candidate": str(candidate_checkpoint) if candidate_checkpoint else config.candidate,
        "opponent": str(opponent_checkpoint) if opponent_checkpoint else config.opponent,
        "games": len(games),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / len(games),
        "seat_0_wins": sum(game["candidate_won"] for game in games if game["candidate_seat"] == 0),
        "seat_1_wins": sum(game["candidate_won"] for game in games if game["candidate_seat"] == 1),
        "average_steps": sum(game["steps"] for game in games) / len(games),
        "average_rounds": sum(game["rounds"] for game in games) / len(games),
        "results": games,
    }


def outcome_counts(games: list[dict]) -> tuple[int, int, int]:
    wins = sum(game["candidate_won"] for game in games)
    draws = sum(game["draw"] for game in games)
    return wins, draws, len(games) - wins - draws


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--candidate-checkpoint", type=Path)
    parser.add_argument("--opponent-checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = evaluate(
        arguments.config,
        arguments.candidate_checkpoint,
        arguments.opponent_checkpoint,
    )
    serialized = json.dumps(result, indent=2)
    if arguments.output is not None:
        arguments.output.write_text(serialized + "\n")
    print(serialized)


if __name__ == "__main__":
    main()
