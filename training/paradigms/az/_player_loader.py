"""Register the lazy AZ checkpoint player loader."""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint

from training.core.matchup.loaders import (
    PlayerBuilder,
    _AgentArgmaxPlayer,
    _AgentMCTSPlayer,
    _PlayerProtocol,
    register_loader,
)
from training.core.network import AgentConfig
from training.paradigms.az.network import Agent


def _load_az_agent_from_ckpt(ckpt_path: str, *, verify_provenance: bool = True) -> Agent:
    """Load an AZ Agent from a checkpoint produced by AZ training.

    Current checkpoints use ``net_state_dict``. The legacy ``net`` key is
    retained for archived checkpoints used by retrospective benchmarks.
    """
    blob = load_checkpoint(
        ckpt_path,
        weights_only=True,
        map_location='cpu',
        verify_provenance=verify_provenance,
    )
    if not isinstance(blob, dict) or 'cfg' not in blob:
        raise RuntimeError(f"matchup: az ckpt {ckpt_path} missing 'cfg' key")
    state_key = 'net_state_dict' if 'net_state_dict' in blob else 'net'
    if state_key not in blob:
        raise RuntimeError(
            f"matchup: az ckpt {ckpt_path} missing 'net_state_dict' key "
            f"or legacy 'net' key; retrain or convert the checkpoint."
        )
    cfg = AgentConfig(**blob['cfg'])
    agent = Agent(cfg)
    agent.net.load_state_dict(blob[state_key])
    agent.net.eval()
    return agent


def _loader_az(spec: dict) -> PlayerBuilder:
    agent = _load_az_agent_from_ckpt(
        spec['ckpt'],
        verify_provenance=not bool(spec.get('allow_unverified_checkpoint', False)),
    )
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
