"""Compatibility stub for the legacy replay checkpoint inspector.

Replay routes still accept an optional ``ckpt`` query parameter, but the old
cross-attention inspector no longer matches current semantic checkpoints.
Current live-play model loading and policy output are implemented in
``web.backend.semantic_live``. Until replay inspection is rebuilt on that
format, this module fails explicitly and the replay API returns ``agent=null``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InspectionResult:
    """Legacy replay API result shape retained for response compatibility."""

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
    """Unavailable legacy replay inspector."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            'Replay checkpoint inspection is unavailable for current semantic '
            'checkpoints; use the live profile for current model inference.'
        )

    def inspect(self, *args, **kwargs) -> InspectionResult:
        raise NotImplementedError
