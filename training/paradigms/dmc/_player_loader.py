"""Register the DMC checkpoint player loader.

Checkpoints use the ``CheckpointManager`` schema and are loaded through
``load_net_state_dict``. DMC has no MCTS prior/value interface, so the
loader accepts only ``n_simulations == 0`` and uses greedy Q selection.
"""

from __future__ import annotations

from typing import Any

from gicg_env import GicgEnv
from training.core.checkpoint import load_net_state_dict
from training.core.matchup.loaders import (
    PlayerBuilder,
    _PlayerProtocol,
    register_loader,
)
from training.core.network import AgentConfig


def _load_dmc_agent(ckpt_path: str) -> Any:
    """Load a DmcAgent from a CheckpointManager-format checkpoint.

    The network shape comes from ``make_dmc_default_shape`` because the
    evaluation adapter does not persist separate shape metadata. A
    non-default checkpoint therefore fails at ``load_state_dict``.
    """
    from training.core.cfg import make_dmc_default_shape
    from training.paradigms.dmc._agent import DmcAgent

    shape = make_dmc_default_shape()
    agent_cfg = AgentConfig.from_obs_shape(shape)
    agent = DmcAgent(agent_cfg, device='cpu', lr=1e-4, epsilon=0.0)
    state_dict = load_net_state_dict(ckpt_path, map_location='cpu')
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


class _DmcArgmaxPlayer:
    """Wrap ``DmcAgent`` as a deterministic gauntlet player.

    ``game_start`` is called when the static observation object changes;
    action selection then follows the agent's epsilon-zero greedy path.
    """

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._last_static_hash: Any = None

    def select_action(self, env: GicgEnv) -> int:
        # ``game_start`` also caches the encoded static observation.
        static_obs = env.static_obs
        h = id(static_obs)  # cheap pre-check;真 hash 在 game_start 内部
        if h != self._last_static_hash:
            self.agent.game_start(static_obs)
            self._last_static_hash = h
        return self.agent.select_action(env)


def _loader_dmc(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise NotImplementedError(
            'DMC player loader does not support n_simulations > 0; omit it or set it to 0 for greedy Q selection.'
        )
    agent = _load_dmc_agent(spec['ckpt'])

    def builder(seed: int) -> _PlayerProtocol:
        return _DmcArgmaxPlayer(agent)

    return builder


register_loader('dmc', _loader_dmc)
