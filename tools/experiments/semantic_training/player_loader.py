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
from tools.experiments.semantic_training.consequence_policy import FORMAT as CONSEQUENCE_FORMAT
from tools.experiments.semantic_training.search_player import SearchPlayer


FORMAT = 'semantic-q/2.0.0'


def load_semantic_payload(ckpt_path: str, *, verify_provenance: bool = True) -> Mapping:
    """Read and validate the persisted semantic-Q envelope and provenance."""
    payload = load_checkpoint(
        ckpt_path,
        map_location='cpu',
        weights_only=False,
        verify_provenance=verify_provenance,
    )
    if not isinstance(payload, Mapping) or payload.get('format') not in (FORMAT, CONSEQUENCE_FORMAT):
        raise ValueError(f'unsupported semantic checkpoint; expected {FORMAT} or {CONSEQUENCE_FORMAT}')
    shape = payload.get('shape')
    state = payload.get('net')
    if not isinstance(shape, Mapping) or not isinstance(state, Mapping):
        raise ValueError('semantic checkpoint is missing shape or net state')
    return payload


def load_semantic_agent(
    ckpt_path: str,
    *,
    seed: int = 0,
    device: str = 'cpu',
    verify_provenance: bool = True,
) -> SemanticAgent:
    """Create one independent inference agent from a compatible checkpoint."""
    payload = load_semantic_payload(ckpt_path, verify_provenance=verify_provenance)
    return _agent_from_payload(payload, seed, device)


def _agent_from_payload(payload: Mapping, seed: int, device: str = 'cpu') -> SemanticAgent:
    shape = payload['shape']
    state = payload['net']
    try:
        agent = SemanticAgent(AgentConfig(**shape), device)
        if payload['format'] == CONSEQUENCE_FORMAT:
            from tools.experiments.semantic_training.consequence_policy import ConsequencePolicyNet
            from tools.experiments.semantic_training.rule_auxiliary import RuleHead

            use_consequences = payload.get('use_consequences')
            if type(use_consequences) is not bool:
                raise ValueError('consequence policy requires explicit boolean use_consequences')
            agent.net = ConsequencePolicyNet(
                agent.net, RuleHead(agent.cfg.d_model), agent.cfg.d_model, use_consequences=use_consequences
            ).to(device)
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
    if 'rule_adapter' in payload:
        from tools.experiments.semantic_training.rule_auxiliary import attach_adapter

        attach_adapter(agent).load_state_dict(payload['rule_adapter'], strict=True)
    return agent


def _loader_semantic(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise ValueError('semantic_rl does not support n_simulations')
    ckpt = spec.get('ckpt')
    if not isinstance(ckpt, str) or not ckpt:
        raise ValueError('semantic_rl requires a checkpoint')
    payload = load_semantic_payload(
        ckpt,
        verify_provenance=not bool(spec.get('allow_unverified_checkpoint', False)),
    )

    def builder(seed: int) -> SemanticAgent:
        return _agent_from_payload(payload, seed)

    return builder


def _loader_search(spec: dict) -> PlayerBuilder:
    """Inference-time search player over a semantic-Q value head.

    Spec keys: ``ckpt`` (required), ``n_beliefs`` (default 2),
    ``mode`` ('value1p' default | 'rollout'), ``rollout_plies``
    (default 8, rollout mode only), ``device`` (default 'cpu')."""
    ckpt = spec.get('ckpt')
    if not isinstance(ckpt, str) or not ckpt:
        raise ValueError('search_policy requires a checkpoint')
    n_beliefs = int(spec.get('n_beliefs', 2))
    mode = str(spec.get('mode', 'value1p'))
    rollout_plies = int(spec.get('rollout_plies', 8))
    n_playouts = int(spec.get('n_playouts', 4))
    device = str(spec.get('device', 'cpu'))
    payload = load_semantic_payload(
        ckpt,
        verify_provenance=not bool(spec.get('allow_unverified_checkpoint', False)),
    )
    if mode != 'playout' and 'value_head' not in payload:
        raise ValueError('value-head modes require a checkpoint with a value_head')

    def builder(seed: int) -> SearchPlayer:
        agent = _agent_from_payload(payload, seed, device)
        return SearchPlayer(
            agent,
            n_beliefs=n_beliefs,
            mode=mode,
            rollout_plies=rollout_plies,
            n_playouts=n_playouts,
            seed=seed,
        )

    return builder


def register_semantic_loader() -> None:
    """Install the experimental adapters in core's loader registry."""
    register_loader('semantic_rl', _loader_semantic)
    register_loader('search_policy', _loader_search)
