import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import torch

from .algorithm import Decision, EpisodicActorCritic
from .config import load_environment_config, load_training_config
from .env import env


def train(
    config_path: Path,
    artifact_root: Path = Path("artifacts"),
    resume: Path | None = None,
) -> Path:
    environment_config = load_environment_config(config_path)
    training_config = load_training_config(config_path)
    torch.manual_seed(environment_config.seed)
    game = env(environment_config)
    algorithm = EpisodicActorCritic(
        game.state_encoder.size,
        game.action_encoder.size,
        training_config,
    )
    start_episode = algorithm.restore(resume, game.rules["hash"]) if resume is not None else 0
    if start_episode >= training_config.episodes:
        raise RuntimeError(
            f"checkpoint is at episode {start_episode}, target is {training_config.episodes}"
        )
    if training_config.checkpoint_every < 1:
        raise RuntimeError("checkpoint_every must be positive")
    run = create_run_directory(artifact_root, training_config.experiment_tag)
    checkpoints = run / "checkpoints"
    checkpoints.mkdir()
    shutil.copy2(config_path, run / "config.toml")
    write_json(
        run / "metadata.json",
        {
            "ruleset": game.rules["hash"],
            "seed": environment_config.seed,
            "state_features": game.state_encoder.size,
            "action_features": game.action_encoder.size,
            "start_episode": start_episode,
            "resume": str(resume.resolve()) if resume is not None else None,
        },
    )
    with (run / "metrics.jsonl").open("w") as metrics_file:
        for episode in range(start_episode, training_config.episodes):
            metrics = train_episode(game, algorithm, environment_config.seed + episode)
            metrics["episode"] = episode + 1
            metrics_file.write(json.dumps(metrics) + "\n")
            metrics_file.flush()
            if (episode + 1) % training_config.checkpoint_every == 0:
                algorithm.checkpoint(
                    checkpoints / f"{episode + 1:06d}.pt",
                    episode + 1,
                    game.rules["hash"],
                )
    algorithm.checkpoint(run / "checkpoint.pt", training_config.episodes, game.rules["hash"])
    game.close()
    return run


def train_episode(game, algorithm: EpisodicActorCritic, seed: int) -> dict:
    trajectories: list[list[Decision]] = [[], []]
    game.reset(seed=seed)
    while game.agents:
        observation, _, terminated, truncated, _ = game.last()
        if terminated or truncated:
            game.step(None)
            continue
        player = game.agent_name_mapping[game.agent_selection]
        action, decision = algorithm.select(observation)
        trajectories[player].append(decision)
        game.step(action)
    if game.state["phase"] != "finished":
        raise RuntimeError(f"episode exceeded {game.config.max_steps} steps")
    metrics = algorithm.update(trajectories, game.state["winner"])
    metrics.update(
        {
            "seed": seed,
            "steps": game.steps,
            "rounds": game.state["round"],
            "winner": game.state["winner"],
        }
    )
    return metrics


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
