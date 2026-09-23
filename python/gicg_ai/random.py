import argparse
import json
from pathlib import Path

import numpy as np

from .env import env


def play(config: Path, episodes: int, seed: int) -> list[dict]:
    game = env(config)
    random = np.random.default_rng(seed)
    results = []
    for episode in range(episodes):
        game.reset(seed=seed + episode)
        while game.agents:
            _, _, terminated, truncated, _ = game.last()
            if terminated or truncated:
                game.step(None)
                continue
            game.step(int(random.integers(len(game.legal_actions))))
        if game.state["phase"] != "finished":
            raise RuntimeError(f"episode {episode} exceeded {game.config.max_steps} steps")
        results.append(
            {
                "episode": episode,
                "seed": seed + episode,
                "steps": game.steps,
                "rounds": game.state["round"],
                "winner": game.state["winner"],
            }
        )
    game.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    arguments = parser.parse_args()
    print(json.dumps(play(arguments.config, arguments.episodes, arguments.seed)))


if __name__ == "__main__":
    main()
