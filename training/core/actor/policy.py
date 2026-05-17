"""EpisodePolicy base class.

Concrete paradigm policies (MCTSPolicy / EpsilonGreedyPolicy / etc.)
subclass this. The base owns the deterministic / epsilon plumbing
that EpisodeRunner reads from EpisodeSpec.
"""

from __future__ import annotations

from typing import Any

from training.core.protocols import NetworkProvider


class EpisodePolicyBase:
    """Base for paradigm-specific actor policies.

    Subclass MUST override ``act(obs, mask, provider)``. ``reset`` is
    optional (no-op base impl) — paradigms like AZ override to clear
    tree state between episodes."""

    def __init__(self, deterministic: bool = False, epsilon: float = 0.0) -> None:
        self.deterministic = deterministic
        self.epsilon = epsilon

    def reset(self) -> None:
        """No-op default. AZ overrides to clear MCTS root."""
        return None

    def act(self, obs: Any, mask: Any, provider: NetworkProvider) -> tuple:
        """Return (action_idx: int, meta: dict).

        meta carries paradigm-specific data (policy logits / mcts visits
        / value pred / action_payments etc.) that the Buffer push
        consumes."""
        raise NotImplementedError('EpisodePolicyBase.act: subclass must override')
