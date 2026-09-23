import argparse
import json
import multiprocessing
import shutil
from dataclasses import dataclass
from datetime import datetime
from multiprocessing.connection import Connection
from pathlib import Path

import numpy as np
import torch

from .algorithm import DmcAlgorithm, Transition, exploration
from .config import (
    EnvironmentConfig,
    TrainingConfig,
    load_environment_config,
    load_training_config,
)
from .env import GicgEnv, env
from .policy import greedy_spec, validate_opponent


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


@dataclass(frozen=True)
class InferenceRequest:
    state: np.ndarray
    actions: np.ndarray


class CentralActors:
    def __init__(self, environment: EnvironmentConfig, config: TrainingConfig):
        context = multiprocessing.get_context("spawn")
        self.connections: list[Connection] = []
        self.processes: list[multiprocessing.Process] = []
        for _ in range(config.actors):
            parent, child = context.Pipe()
            process = context.Process(target=actor_loop, args=(child, environment, config))
            process.start()
            child.close()
            self.connections.append(parent)
            self.processes.append(process)

    def collect(
        self, algorithm: DmcAlgorithm, episodes: range
    ) -> list[tuple[EpisodeRollout, dict]]:
        active = self.connections[: len(episodes)]
        for connection, episode in zip(active, episodes, strict=True):
            connection.send(episode)
        completed = []
        while active:
            messages = [(connection, connection.recv()) for connection in active]
            requests = []
            active = []
            for connection, message in messages:
                if isinstance(message, EpisodeRollout):
                    completed.append((message, learn_rollout(algorithm, message)))
                elif isinstance(message, InferenceRequest):
                    requests.append((connection, message))
                    active.append(connection)
                else:
                    raise RuntimeError(f"unknown actor message {type(message)!r}")
            self._respond(algorithm, requests)
        return sorted(completed, key=lambda item: item[0].episode)

    @staticmethod
    def _respond(
        algorithm: DmcAlgorithm, requests: list[tuple[Connection, InferenceRequest]]
    ) -> None:
        if not requests:
            return
        observations = [(request.state, request.actions) for _, request in requests]
        selections = algorithm.select_batch(observations)
        for (connection, _), selected in zip(requests, selections, strict=True):
            connection.send(selected)

    def close(self) -> None:
        for connection in self.connections:
            connection.send(None)
        for process in self.processes:
            process.join()
            if process.exitcode != 0:
                raise RuntimeError(f"actor process exited with code {process.exitcode}")
        for connection in self.connections:
            connection.close()

    def __enter__(self) -> "CentralActors":
        return self

    def __exit__(self, error_type, error, traceback) -> None:
        self.close()


def train(
    config_path: Path,
    artifact_root: Path = Path("artifacts"),
    resume: Path | None = None,
    overrides: tuple[str, ...] = (),
) -> Path:
    environment_config = load_environment_config(config_path, overrides)
    training_config = load_training_config(config_path, overrides)
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
    write_metadata(run, game, environment_config.seed, start_episode, resume, overrides)
    with (
        CentralActors(environment_config, training_config) as actors,
        (run / "metrics.jsonl").open("w") as metrics_file,
    ):
        episode = start_episode
        while episode < training_config.episodes:
            end = wave_end(episode, training_config)
            for _, metrics in actors.collect(algorithm, range(episode, end)):
                metrics_file.write(json.dumps(metrics) + "\n")
                metrics_file.flush()
            episode = end
            checkpoint_if_needed(
                algorithm,
                checkpoints,
                episode,
                game.rules["hash"],
                training_config,
            )
    algorithm.checkpoint(run / "checkpoint.pt", training_config.episodes, game.rules["hash"])
    game.close()
    return run


def actor_loop(
    connection: Connection, environment: EnvironmentConfig, config: TrainingConfig
) -> None:
    torch.set_num_threads(1)
    game = env(environment)
    while (episode := connection.recv()) is not None:
        connection.send(
            collect_episode(game, config, environment.seed + episode, episode, connection)
        )
    game.close()
    connection.close()


def collect_episode(
    game: GicgEnv,
    config: TrainingConfig,
    seed: int,
    episode: int,
    connection: Connection,
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
            action, transition = learner_action(observation, epsilon, random, connection)
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


def learner_action(
    observation: dict[str, np.ndarray],
    epsilon: float,
    random: np.random.Generator,
    connection: Connection,
) -> tuple[int, Transition]:
    count = int(observation["action_mask"].sum())
    if count == 0:
        raise RuntimeError("policy received no legal actions")
    if random.random() < epsilon:
        selected = int(random.integers(count))
    else:
        connection.send(
            InferenceRequest(observation["state"].copy(), observation["actions"][:count].copy())
        )
        selected = connection.recv()
    return selected, Transition(
        state=observation["state"].copy(),
        action=observation["actions"][selected].copy(),
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


def wave_end(episode: int, config: TrainingConfig) -> int:
    checkpoint = ((episode // config.checkpoint_every) + 1) * config.checkpoint_every
    return min(config.episodes, episode + config.actors, checkpoint)


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
    features, depth = greedy_spec(opponent)
    seed = int(random.integers(0, np.iinfo(np.uint64).max, dtype=np.uint64))
    return game.select_greedy_action(features, depth, config.opponent_node_budget, seed)


def select_opponent(config: TrainingConfig, random: np.random.Generator) -> str:
    policies = [opponent.policy for opponent in config.opponents]
    weights = [opponent.weight for opponent in config.opponents]
    return str(random.choice(policies, p=weights))


def validate_training_config(config: TrainingConfig) -> None:
    positive = {
        "episodes": config.episodes,
        "actors": config.actors,
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
    validate_opponents(config)


def validate_opponents(config: TrainingConfig) -> None:
    if not config.opponents:
        raise RuntimeError("at least one opponent is required")
    for opponent in config.opponents:
        validate_opponent(opponent.policy)
    if any(opponent.weight <= 0 for opponent in config.opponents):
        raise RuntimeError("opponent weights must be positive")
    weights = sum(opponent.weight for opponent in config.opponents)
    if not np.isclose(weights, 1.0):
        raise RuntimeError(f"opponent weights must sum to 1, got {weights}")


def write_metadata(
    run: Path,
    game: GicgEnv,
    seed: int,
    start_episode: int,
    resume: Path | None,
    overrides: tuple[str, ...],
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
            "overrides": list(overrides),
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
    parser.add_argument("--set", action="append", default=[])
    arguments = parser.parse_args()
    print(
        train(
            arguments.config,
            arguments.artifacts,
            arguments.resume,
            tuple(arguments.set),
        )
    )


if __name__ == "__main__":
    main()
