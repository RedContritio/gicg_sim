"""Matchup adapter for strict semantic-Q checkpoint loading.

Composition roots import this module explicitly to register the experimental
model.  Core never imports ``tools`` in the opposite direction.
"""

from __future__ import annotations

from collections.abc import Mapping

from training.core.artifact_io import load_checkpoint
from training.core.matchup.loaders import PlayerBuilder, register_loader
from training.core.network import AgentConfig
from tools.experiments.semantic_training.agent import SemanticAgent


FORMAT = 'semantic-q/2.0.0'


def load_semantic_payload(ckpt_path: str) -> Mapping:
    """Read and validate the persisted semantic-Q envelope and provenance."""
    payload = load_checkpoint(ckpt_path, map_location='cpu', weights_only=False)
    if not isinstance(payload, Mapping) or payload.get('format') != FORMAT:
        raise ValueError(f'unsupported semantic checkpoint; expected {FORMAT}')
    shape = payload.get('shape')
    state = payload.get('net')
    if not isinstance(shape, Mapping) or not isinstance(state, Mapping):
        raise ValueError('semantic checkpoint is missing shape or net state')
    return payload


def load_semantic_agent(ckpt_path: str, *, seed: int = 0) -> SemanticAgent:
    """Create one independent inference agent from a compatible checkpoint."""
    payload = load_semantic_payload(ckpt_path)
    return _agent_from_payload(payload, seed)


def _agent_from_payload(payload: Mapping, seed: int) -> SemanticAgent:
    shape = payload['shape']
    state = payload['net']
    try:
        agent = SemanticAgent(AgentConfig(**shape))
        agent.net.load_state_dict(state, strict=True)
    except (TypeError, RuntimeError) as exc:
        raise ValueError('semantic checkpoint shape or net state is incompatible') from exc
    agent.net.eval()
    agent.rng.seed(seed)
    settings = payload.get('settings', {})
    agent.sampling_temperature = settings.get('temperature', 1.0) if isinstance(settings, Mapping) else 1.0
    if 'value_head' in payload:
        from tools.experiments.semantic_training.value_baseline import attach

        attach(agent, payload['value_head']).eval()
    return agent


def _loader_semantic(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise ValueError('semantic_rl does not support n_simulations')
    ckpt = spec.get('ckpt')
    if not isinstance(ckpt, str) or not ckpt:
        raise ValueError('semantic_rl requires a checkpoint')
    payload = load_semantic_payload(ckpt)

    def builder(seed: int) -> SemanticAgent:
        return _agent_from_payload(payload, seed)

    return builder


def register_semantic_loader() -> None:
    """Install the experimental adapter in core's loader registry."""
    register_loader('semantic_rl', _loader_semantic)
