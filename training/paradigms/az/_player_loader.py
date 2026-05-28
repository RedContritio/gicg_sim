"""AZ player loader — registers ``'az'`` factory with
``training.core.matchup.loaders`` registry。 Imported by core's lazy
loader on first ``load_player({'type': 'az', ...})`` (W2-1).

Pre-W2-1 this code lived inline at ``core/matchup/loaders.py`` as
``_loader_az`` + ``_load_agent_from_ckpt``;the inline placement made
core statically depend on ``training.paradigms.az.network.Agent``
(audit finding 高优 #1 — violated ADR-0006 单向依赖)。 Moved here so
that path becomes lazy + paradigm-local。
"""

from __future__ import annotations

import torch

from training.core.matchup.loaders import (
    PlayerBuilder,
    _AgentArgmaxPlayer,
    _AgentMCTSPlayer,
    _PlayerProtocol,
    register_loader,
)
from training.core.network import AgentConfig
from training.paradigms.az.network import Agent


def _load_az_agent_from_ckpt(ckpt_path: str) -> Agent:
    """Load an AZ Agent from a ckpt blob produced by AZ training。

    Supports both the new ``net_state_dict`` key (post
    core-network-generic-promotion N4 schema) and the legacy ``net``
    key — the latter was removed by Phase 0 (2026-05-17) but earlier
    pre-redesign archives may still surface in retro-bench runs。
    """
    blob = torch.load(ckpt_path, weights_only=True, map_location='cpu')
    if not isinstance(blob, dict) or 'cfg' not in blob:
        raise RuntimeError(f"matchup: az ckpt {ckpt_path} missing 'cfg' key")
    state_key = 'net_state_dict' if 'net_state_dict' in blob else 'net'
    if state_key not in blob:
        raise RuntimeError(
            f"matchup: az ckpt {ckpt_path} missing 'net_state_dict' key "
            f'(post core-network-generic-promotion Phase 0 schema); retrain to new schema.'
        )
    cfg = AgentConfig(**blob['cfg'])
    agent = Agent(cfg)
    agent.net.load_state_dict(blob[state_key])
    agent.net.eval()
    return agent


def _loader_az(spec: dict) -> PlayerBuilder:
    agent = _load_az_agent_from_ckpt(spec['ckpt'])
    n_sims = int(spec.get('n_simulations', 0))
    max_depth = int(spec.get('max_rollout_depth', 400))

    def builder(seed: int) -> _PlayerProtocol:
        if n_sims == 0:
            return _AgentArgmaxPlayer(agent)
        return _AgentMCTSPlayer(
            agent,
            n_rollouts=n_sims,
            seed=seed,
            max_rollout_depth=max_depth,
        )

    return builder


register_loader('az', _loader_az)
