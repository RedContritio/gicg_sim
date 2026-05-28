"""CFR player loader — registers ``'cfr'`` factory with
``training.core.matchup.loaders`` registry。 Imported by core's lazy
loader on first ``load_player({'type': 'cfr', ...})`` (W2-1).

Pre-W2-1 this code lived inline at ``core/matchup/loaders.py`` as
``_loader_cfr``;the inline placement made core statically depend on
``training.paradigms.cfr.agent.CFRAgent`` + ``CFRNetConfig`` (audit
finding 高优 #1 — violated ADR-0006 单向依赖)。 Moved here so that
path becomes lazy + paradigm-local。

n_simulations == 0 → argmax over strategy head。
n_simulations > 0 → MCTS(net prior + value) via the same
``_AgentMCTSPlayer`` wrapper used for AZ。 The MCTS impl 本身仍住
``paradigms.az.mcts`` —— 这是 W2-1 范围外的 deeper layout issue。
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
from training.paradigms.cfr.agent import CFRAgent
from training.paradigms.cfr.strategy_net import CFRNetConfig


def _loader_cfr(spec: dict) -> PlayerBuilder:
    ckpt_path = spec['ckpt']
    blob = torch.load(ckpt_path, weights_only=True, map_location='cpu')
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
