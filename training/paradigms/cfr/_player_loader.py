"""Register the lazy CFR checkpoint player loader.

``n_simulations == 0`` uses greedy strategy-head selection. A positive
budget wraps the agent with the shared MCTS player, whose search
implementation currently lives in ``training.paradigms.az.mcts``.
"""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint

import torch

from training.core.matchup.loaders import (
    PlayerBuilder,
    _AgentArgmaxPlayer,
    _AgentMCTSPlayer,
    _PlayerProtocol,
    register_loader,
)
from training.paradigms.cfr.agent import CFRAgent
from training.paradigms.cfr.strategy_net import CFRNetConfig


def _loader_cfr(spec: dict) -> PlayerBuilder:
    ckpt_path = spec['ckpt']
    blob = load_checkpoint(ckpt_path, weights_only=True, map_location='cpu')
    if not isinstance(blob, dict) or 'cfg' not in blob or 'net' not in blob:
        raise RuntimeError(f"matchup: cfr ckpt {ckpt_path} missing 'cfg' or 'net' key")
    cfg = CFRNetConfig(**blob['cfg'])
    agent = CFRAgent(cfg)
    agent.net.load_state_dict(blob['net'])
    agent.net.eval()

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


register_loader('cfr', _loader_cfr)
