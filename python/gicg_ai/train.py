import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from .algorithm import DmcAlgorithm, Transition, exploration
from .config import TrainingConfig, load_environment_config, load_training_config
from .env import GicgEnv, env


def train(
    config_path: Path,
    artifact_root: Path = Path("artifacts"),
    resume: Path | None = None,
) -> Path:
    environment_config = load_environment_config(config_path)
    training_config = load_training_config(config_path)
    validate_training_config(training_config)
    torch.manual_seed(environment_config.seed)
    game = env(environment_config)
    algorithm = DmcAlgorithm(
        game.state_encoder.size,
        game.action_encoder.size,
        training_config,
        environment_config.seed,
    )
    start_episode = algorithm.restore(resume, game.rules["hash"]) if resume is not None else 0
    if start_episode >= training_config.episodes:
        raise RuntimeError(
            f"checkpoint is at episode {start_episode}, target is {training_config.episodes}"
        )
    run = create_run_directory(artifact_root, training_config.experiment_tag)
    checkpoints = run / "checkpoints"
    checkpoints.mkdir()
    shutil.copy2(config_path, run / "config.toml")
    write_metadata(run, game, environment_config.seed, start_episode, resume)
    with (run / "metrics.jsonl").open("w") as metrics_file:
        for episode in range(start_episode, training_config.episodes):
            metrics = train_episode(
                game,
                algorithm,
                training_config,
                environment_config.seed + episode,
                episode,
            )
            metrics["episode"] = episode + 1
            metrics_file.write(json.dumps(metrics) + "\n")
            metrics_file.flush()
            if (episode + 1) % training_config.checkpoint_every == 0:
                algorithm.checkpoint(
                    checkpoints / f"{episode + 1:06d}.pt",
                    episode + 1,
                    game.rules["hash"],
                )
                prune_checkpoints(checkpoints, training_config.keep_checkpoints)
    algorithm.checkpoint(run / "checkpoint.pt", training_config.episodes, game.rules["hash"])
    game.close()
    return run


def train_episode(
    game: GicgEnv,
    algorithm: DmcAlgorithm,
    config: TrainingConfig,
    seed: int,
    episode: int,
) -> dict:
    random = np.random.default_rng(seed)
    learner = episode % 2
    epsilon = exploration(config, episode)
    opponent = select_opponent(config, random)
    transitions: list[Transition] = []
    game.reset(seed=seed)
    while game.state["phase"] != "finished":
        observation, _, terminated, truncated, _ = game.last()
        if terminated or truncated:
            break
        player = game.agent_name_mapping[game.agent_selection]
        if player == learner:
            action, transition = algorithm.select(observation, epsilon, random)
            transitions.append(transition)
        else:
            action = opponent_action(game, config, opponent, random)
        game.step(action)
    winner = game.state.get("winner")
    outcome = 0.0 if winner is None else (1.0 if winner == learner else -1.0)
    metrics = algorithm.learn_episode(transitions, outcome)
    metrics.update(
        {
            "seed": seed,
            "steps": game.steps,
            "rounds": game.state["round"],
            "winner": winner,
            "truncated": winner is None,
            "learner": learner,
            "opponent": opponent,
            "outcome": outcome,
            "epsilon": epsilon,
        }
    )
    return metrics


def opponent_action(
    game: GicgEnv,
    config: TrainingConfig,
    opponent: str,
    random: np.random.Generator,
) -> int:
    if opponent == "random":
        return int(random.integers(len(game.legal_actions)))
    seed = int(random.integers(0, np.iinfo(np.uint64).max, dtype=np.uint64))
    return game.select_greedy_action(1, 2, config.opponent_node_budget, seed)


def select_opponent(config: TrainingConfig, random: np.random.Generator) -> str:
    if random.random() < config.random_opponent_weight:
        return "random"
    return "F1D2"


def validate_training_config(config: TrainingConfig) -> None:
    positive = {
        "episodes": config.episodes,
        "batch_size": config.batch_size,
        "replay_capacity": config.replay_capacity,
        "updates_per_episode": config.updates_per_episode,
        "epsilon_decay_episodes": config.epsilon_decay_episodes,
        "checkpoint_every": config.checkpoint_every,
        "keep_checkpoints": config.keep_checkpoints,
        "opponent_node_budget": config.opponent_node_budget,
    }
    invalid = [name for name, value in positive.items() if value < 1]
    if invalid:
        raise RuntimeError(f"training values must be positive: {', '.join(invalid)}")
    if config.batch_size > config.replay_capacity:
        raise RuntimeError("batch_size cannot exceed replay_capacity")
    if not 0 <= config.epsilon_end <= config.epsilon_start <= 1:
        raise RuntimeError("epsilon must satisfy 0 <= end <= start <= 1")
    if config.max_grad_norm <= 0:
        raise RuntimeError("max_grad_norm must be positive")
    weights = config.random_opponent_weight + config.f1d2_opponent_weight
    if config.random_opponent_weight < 0 or config.f1d2_opponent_weight < 0:
        raise RuntimeError("opponent weights cannot be negative")
    if not np.isclose(weights, 1.0):
        raise RuntimeError(f"opponent weights must sum to 1, got {weights}")


def write_metadata(
    run: Path,
    game: GicgEnv,
    seed: int,
    start_episode: int,
    resume: Path | None,
) -> None:
    write_json(
        run / "metadata.json",
        {
            "algorithm": "dmc",
            "ruleset": game.rules["hash"],
            "seed": seed,
            "state_features": game.state_encoder.size,
            "action_features": game.action_encoder.size,
            "start_episode": start_episode,
            "resume": str(resume.resolve()) if resume is not None else None,
        },
    )


def create_run_directory(root: Path, tag: str) -> Path:
    parent = root / tag
    parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    for sequence in range(1, 1_000_000):
        run = parent / f"{timestamp}_{sequence:06d}"
        try:
            run.mkdir()
        except FileExistsError:
            continue
        return run
    raise RuntimeError("experiment sequence is exhausted")


def prune_checkpoints(directory: Path, keep: int) -> None:
    checkpoints = sorted(directory.glob("*.pt"))
    for checkpoint in checkpoints[:-keep]:
        checkpoint.unlink()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--resume", type=Path)
    arguments = parser.parse_args()
    print(train(arguments.config, arguments.artifacts, arguments.resume))


if __name__ == "__main__":
    main()
