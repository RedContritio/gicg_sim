import argparse
import json
import multiprocessing
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from .algorithm import DmcAlgorithm, DmcQNetwork, Transition, exploration, select_action
from .config import (
    EnvironmentConfig,
    TrainingConfig,
    load_environment_config,
    load_training_config,
)
from .env import GicgEnv, env

_actor_game: GicgEnv | None = None
_actor_model: DmcQNetwork | None = None
_actor_config: TrainingConfig | None = None


@dataclass(frozen=True)
class EpisodeRollout:
    episode: int
    seed: int
    learner: int
    opponent: str
    epsilon: float
    transitions: list[Transition]
    steps: int
    rounds: int
    winner: int | None
    truncated: bool

    @property
    def outcome(self) -> float:
        if self.winner is None:
            return 0.0
        return 1.0 if self.winner == self.learner else -1.0


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
    context = multiprocessing.get_context("spawn")
    with (
        ProcessPoolExecutor(
            max_workers=training_config.actors,
            mp_context=context,
            initializer=initialize_actor,
            initargs=(
                environment_config,
                training_config,
                game.state_encoder.size,
                game.action_encoder.size,
            ),
        ) as actors,
        (run / "metrics.jsonl").open("w") as metrics_file,
    ):
        episode = start_episode
        while episode < training_config.episodes:
            end = rollout_batch_end(episode, training_config)
            rollouts = collect_rollouts(
                actors,
                training_config.actors,
                algorithm.actor_state(),
                range(episode, end),
            )
            for rollout in rollouts:
                metrics = learn_rollout(algorithm, rollout)
                metrics_file.write(json.dumps(metrics) + "\n")
                metrics_file.flush()
                checkpoint_if_needed(
                    algorithm,
                    checkpoints,
                    rollout.episode + 1,
                    game.rules["hash"],
                    training_config,
                )
            episode = end
    algorithm.checkpoint(run / "checkpoint.pt", training_config.episodes, game.rules["hash"])
    game.close()
    return run


def initialize_actor(
    environment: EnvironmentConfig,
    config: TrainingConfig,
    state_size: int,
    action_size: int,
) -> None:
    global _actor_game, _actor_model, _actor_config
    torch.set_num_threads(1)
    _actor_game = env(environment)
    _actor_model = DmcQNetwork(state_size, action_size, config.hidden_size)
    _actor_model.eval()
    _actor_config = config


def collect_actor_rollouts(
    model_state: dict[str, np.ndarray], episodes: list[int]
) -> list[EpisodeRollout]:
    if _actor_game is None or _actor_model is None or _actor_config is None:
        raise RuntimeError("actor process is not initialized")
    _actor_model.load_state_dict(
        {name: torch.from_numpy(value) for name, value in model_state.items()}, strict=True
    )
    seed = _actor_game.config.seed
    return [
        collect_episode(_actor_game, _actor_model, _actor_config, seed + episode, episode)
        for episode in episodes
    ]


def collect_episode(
    game: GicgEnv,
    model: DmcQNetwork,
    config: TrainingConfig,
    seed: int,
    episode: int,
) -> EpisodeRollout:
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
            action, transition = select_action(
                model, torch.device("cpu"), observation, epsilon, random
            )
            transitions.append(transition)
        else:
            action = opponent_action(game, config, opponent, random)
        game.step(action)
    winner = game.state.get("winner")
    return EpisodeRollout(
        episode=episode,
        seed=seed,
        learner=learner,
        opponent=opponent,
        epsilon=epsilon,
        transitions=transitions,
        steps=game.steps,
        rounds=game.state["round"],
        winner=winner,
        truncated=any(game.truncations.values()),
    )


def learn_rollout(algorithm: DmcAlgorithm, rollout: EpisodeRollout) -> dict:
    metrics = algorithm.learn_episode(rollout.transitions, rollout.outcome)
    metrics.update(
        {
            "seed": rollout.seed,
            "steps": rollout.steps,
            "rounds": rollout.rounds,
            "winner": rollout.winner,
            "truncated": rollout.truncated,
            "learner": rollout.learner,
            "opponent": rollout.opponent,
            "outcome": rollout.outcome,
            "epsilon": rollout.epsilon,
            "episode": rollout.episode + 1,
        }
    )
    return metrics


def rollout_batch_end(episode: int, config: TrainingConfig) -> int:
    checkpoint = ((episode // config.checkpoint_every) + 1) * config.checkpoint_every
    return min(config.episodes, episode + config.rollout_batch_size, checkpoint)


def collect_rollouts(
    actors: ProcessPoolExecutor,
    actor_count: int,
    model_state: dict[str, np.ndarray],
    episodes: range,
) -> list[EpisodeRollout]:
    episode_list = list(episodes)
    count = min(actor_count, len(episode_list))
    chunks = [episode_list[index::count] for index in range(count)]
    futures = [actors.submit(collect_actor_rollouts, model_state, chunk) for chunk in chunks]
    rollouts = [rollout for future in futures for rollout in future.result()]
    return sorted(rollouts, key=lambda rollout: rollout.episode)


def checkpoint_if_needed(
    algorithm: DmcAlgorithm,
    directory: Path,
    episode: int,
    ruleset: str,
    config: TrainingConfig,
) -> None:
    if episode % config.checkpoint_every != 0:
        return
    algorithm.checkpoint(directory / f"{episode:06d}.pt", episode, ruleset)
    prune_checkpoints(directory, config.keep_checkpoints)


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
        "actors": config.actors,
        "rollout_batch_size": config.rollout_batch_size,
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
    validate_parallel_config(config)
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


def validate_parallel_config(config: TrainingConfig) -> None:
    if config.rollout_batch_size < config.actors:
        raise RuntimeError("rollout_batch_size cannot be smaller than actors")


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
