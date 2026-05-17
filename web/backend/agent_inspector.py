"""Checkpoint inference stub.

The PPO-era inspector (which ran `Agent.net(obs)` and captured cross-
attention through a monkey-patched forward hook) is gone. The AZ
replacement — which surfaces MCTS visit distributions, root value,
per-legal-action prior, and search-tree snapshots — is built as part
of task #150 (post-C1 web work), after the AZ training stack produces
its first usable checkpoint.

Until then, any live-play or replay flow that asks for ckpt
inspection raises a clear error instead of silently degrading. The
rest of the web backend (replay viewer, non-ckpt live play) is
unaffected — this file only gates the "with checkpoint" code path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InspectionResult:
    """Kept as a stable type so web API routes can reference it in
    type hints. The fields match what the AZ inspector will produce;
    they stay empty until task #150 lands."""

    value: float = 0.0
    entropy: float = 0.0
    policy: list = None
    top_k: list = None
    attention: list = None
    legal_actions: list = None

    def __post_init__(self):
        for name in ('policy', 'top_k', 'attention', 'legal_actions'):
            if getattr(self, name) is None:
                setattr(self, name, [])


class AgentInspector:
    """Stub placeholder. Instantiating it raises — callers must guard
    their ckpt-inspection code path until the AZ inspector lands."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            'AgentInspector is disabled during the AZ migration. '
            'The PPO inspector has been removed; the AZ replacement '
            'ships with task #150 after the first AZ checkpoint from '
            'C1 is available. Use the replay viewer without --ckpt '
            'or disable live-play ckpt inspection until then.'
        )

    def inspect(self, *args, **kwargs) -> InspectionResult:
        raise NotImplementedError
