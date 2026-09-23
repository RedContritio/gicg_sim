import json
from numbers import Integral
from pathlib import Path

import gymnasium.spaces as spaces
import numpy as np
from gymnasium.utils import seeding
from pettingzoo import AECEnv

from gicg_env import GameSession

from .config import EnvironmentConfig, load_environment_config
from .encoding import ActionEncoder, ObservationEncoder


class GicgEnv(AECEnv):
    metadata = {"name": "gicg_v0", "render_modes": ["ansi"], "is_parallelizable": False}

    def __init__(self, config: EnvironmentConfig, render_mode: str | None = None):
        super().__init__()
        self.config = config
        self.render_mode = render_mode
        self.possible_agents = ["player_0", "player_1"]
        self.agent_name_mapping = {agent: index for index, agent in enumerate(self.possible_agents)}
        catalog = self._new_session(config.seed)
        self.rules = json.loads(catalog.rules_json())
        self.state_encoder = ObservationEncoder(
            self.rules, config.match.format[0], config.match.format[1]
        )
        self.action_encoder = ActionEncoder(self.rules)
        self._action_space = spaces.Discrete(config.max_actions)
        self._observation_space = spaces.Dict(
            {
                "state": spaces.Box(0, 1, (self.state_encoder.size,), dtype=np.float32),
                "actions": spaces.Box(
                    0,
                    1,
                    (config.max_actions, self.action_encoder.size),
                    dtype=np.float32,
                ),
                "action_mask": spaces.MultiBinary(config.max_actions),
            }
        )
        self.session: GameSession | None = None
        self.state: dict = {}
        self.legal_actions: list[dict] = []
        self.steps = 0

    def observation_space(self, agent: str) -> spaces.Space:
        self._require_agent(agent)
        return self._observation_space

    def action_space(self, agent: str) -> spaces.Space:
        self._require_agent(agent)
        return self._action_space

    def reset(self, seed: int | None = None, options: dict | None = None) -> None:
        del options
        if seed is not None:
            self.np_random, _ = seeding.np_random(seed)
        episode_seed = self.config.seed if seed is None else seed
        self.session = self._new_session(episode_seed)
        self.agents = self.possible_agents[:]
        self.rewards = dict.fromkeys(self.agents, 0.0)
        self._cumulative_rewards = dict.fromkeys(self.agents, 0.0)
        self.terminations = dict.fromkeys(self.agents, False)
        self.truncations = dict.fromkeys(self.agents, False)
        self.infos = {agent: {} for agent in self.agents}
        self.steps = 0
        self._refresh()

    def observe(self, agent: str) -> dict[str, np.ndarray]:
        viewer = self.agent_name_mapping[agent]
        actions = np.zeros((self.config.max_actions, self.action_encoder.size), dtype=np.float32)
        for index, action in enumerate(self.legal_actions):
            actions[index] = self.action_encoder.encode(action, self.state)
        mask = np.zeros(self.config.max_actions, dtype=np.int8)
        mask[: len(self.legal_actions)] = 1
        return {
            "state": self.state_encoder.encode(self.state, viewer),
            "actions": actions,
            "action_mask": mask,
        }

    def step(self, action: int | None) -> None:
        if self.terminations[self.agent_selection] or self.truncations[self.agent_selection]:
            self._was_dead_step(action)
            return
        if not isinstance(action, Integral) or not 0 <= action < len(self.legal_actions):
            raise ValueError(f"action must be an integer in [0, {len(self.legal_actions)})")
        agent = self.agent_selection
        self._cumulative_rewards[agent] = 0
        self._clear_rewards()
        selected = self.legal_actions[int(action)]
        self.state = json.loads(self._active_session().act(json.dumps(selected)))
        self.steps += 1
        self._finish_if_needed()
        self._set_controller()
        self._set_legal_actions()
        self._accumulate_rewards()
        if self.terminations[agent] or self.truncations[agent]:
            self._deads_step_first()

    def render(self) -> str:
        winner = self.state.get("winner")
        if winner is not None:
            return f"round={self.state['round']} winner=player_{winner}"
        return (
            f"round={self.state['round']} phase={self.state['phase']} "
            f"controller={self.agent_selection} actions={len(self.legal_actions)}"
        )

    def close(self) -> None:
        self.session = None

    def _new_session(self, seed: int) -> GameSession:
        match = self.config.match
        return GameSession(
            match.ruleset,
            match.players[0],
            match.players[1],
            match.decks,
            match.format,
            seed & ((1 << 64) - 1),
            match.first,
        )

    def _refresh(self) -> None:
        self.state = json.loads(self._active_session().snapshot_json())
        self._set_controller()
        self._set_legal_actions()

    def _set_controller(self) -> None:
        controller = (
            self.state["decision"]["player"] if self.state["decision"] else self.state["turn"]
        )
        self.agent_selection = self.possible_agents[controller]

    def _set_legal_actions(self) -> None:
        if self.state["phase"] == "finished":
            self.legal_actions = []
        else:
            self.legal_actions = json.loads(self._active_session().legal_actions_json())
        if len(self.legal_actions) > self.config.max_actions:
            raise RuntimeError(
                f"state has {len(self.legal_actions)} legal actions, maximum is "
                f"{self.config.max_actions}"
            )
        if self.agents and not self.legal_actions and self.state["phase"] != "finished":
            raise RuntimeError("live state has no legal actions")
        for agent in self.agents:
            self.infos[agent] = {
                "legal_actions": self.legal_actions if agent == self.agent_selection else []
            }

    def _finish_if_needed(self) -> None:
        if self.state["phase"] == "finished":
            self.terminations = dict.fromkeys(self.agents, True)
            winner = self.state["winner"]
            self.rewards[self.possible_agents[winner]] = 1.0
            self.rewards[self.possible_agents[1 - winner]] = -1.0
        elif self.steps >= self.config.max_steps:
            self.truncations = dict.fromkeys(self.agents, True)

    def _active_session(self) -> GameSession:
        if self.session is None:
            raise RuntimeError("environment must be reset before use")
        return self.session

    def _require_agent(self, agent: str) -> None:
        if agent not in self.agent_name_mapping:
            raise KeyError(agent)


def env(config: str | Path | EnvironmentConfig, render_mode: str | None = None) -> GicgEnv:
    settings = (
        load_environment_config(Path(config))
        if not isinstance(config, EnvironmentConfig)
        else config
    )
    return GicgEnv(settings, render_mode)
