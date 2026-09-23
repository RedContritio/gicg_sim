import argparse
import json
from pathlib import Path
from typing import Protocol

import numpy as np
import torch

from .algorithm import CandidateActorCritic, load_policy
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


class HeuristicPolicy:
    priority = {
        "skill": 5,
        "card": 4,
        "tune": 3,
        "switch": 2,
        "end": 1,
    }

    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int:
        del observation
        return max(
            range(len(game.legal_actions)),
            key=lambda index: self.priority.get(game.legal_actions[index]["kind"], 0),
        )


class CheckpointPolicy:
    def __init__(self, model: CandidateActorCritic, device: str):
        self.model = model
        self.device = torch.device(device)

    def select(self, observation: dict[str, np.ndarray], game: GicgEnv) -> int:
        del game
        count = int(observation["action_mask"].sum())
        state = torch.as_tensor(observation["state"], device=self.device)
        actions = torch.as_tensor(observation["actions"][:count], device=self.device)
        with torch.no_grad():
            logits, _ = self.model(state, actions)
        return int(logits.argmax().item())


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
    )
    opponent = create_policy(
        evaluation_config.opponent,
        opponent_checkpoint,
        game,
        evaluation_config.device,
        random,
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
    if name == "heuristic":
        return HeuristicPolicy()
    raise RuntimeError(f"unknown policy {name!r}")


def play_game(game: GicgEnv, policies: list[Policy], seed: int, candidate_seat: int) -> dict:
    game.reset(seed=seed)
    while game.state["phase"] != "finished":
        observation, _, terminated, truncated, _ = game.last()
        if terminated:
            break
        if truncated:
            raise RuntimeError(f"evaluation exceeded {game.config.max_steps} steps")
        player = game.agent_name_mapping[game.agent_selection]
        game.step(policies[player].select(observation, game))
    return {
        "seed": seed,
        "candidate_seat": candidate_seat,
        "winner": game.state["winner"],
        "candidate_won": game.state["winner"] == candidate_seat,
        "steps": game.steps,
        "rounds": game.state["round"],
    }


def summarize(
    games: list[dict],
    config: EvaluationConfig,
    candidate_checkpoint: Path | None,
    opponent_checkpoint: Path | None,
) -> dict:
    wins = sum(game["candidate_won"] for game in games)
    return {
        "candidate": str(candidate_checkpoint) if candidate_checkpoint else config.candidate,
        "opponent": str(opponent_checkpoint) if opponent_checkpoint else config.opponent,
        "games": len(games),
        "wins": wins,
        "losses": len(games) - wins,
        "win_rate": wins / len(games),
        "seat_0_wins": sum(game["candidate_won"] for game in games if game["candidate_seat"] == 0),
        "seat_1_wins": sum(game["candidate_won"] for game in games if game["candidate_seat"] == 1),
        "average_steps": sum(game["steps"] for game in games) / len(games),
        "average_rounds": sum(game["rounds"] for game in games) / len(games),
        "results": games,
    }


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
