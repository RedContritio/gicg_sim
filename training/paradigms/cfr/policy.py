"""CFREpisodePolicy — protocol stub for the CFR paradigm.

Spec ref: paradigm-cfr/spec.md C5. CFR collection runs OS-MCCFR
**traversal** (game-tree recursion) rather than episode rollout —
``EpisodeRunner.run`` is *not* on CFR's hot path, so this policy class
exists only to satisfy the ``EpisodePolicy`` protocol shape that
``Paradigm.make_episode_policy`` is declared to return.

The traversal logic itself lives in
``training.paradigms.cfr.traversal.traverser.CFRTraverser`` and is driven by
``CFRTraversalCollector.collect`` directly, bypassing ``act``. Calling
``act`` here therefore raises — surfacing accidental routing through
``EpisodeRunner`` instead of silently returning a meaningless action
(per global instruction §2.5: contracts strict, errors visible).
"""

from __future__ import annotations

from typing import Any


class CFREpisodePolicy:
    """Stub policy. CFR does not rollout episodes; calling act → raises."""

    # Schema tag — buffer side keys are produced by the traversal,
    # not by act/finalize. Kept for symmetry with DMC adapter.
    transition_schema = 'cfr_traversal_sample'

    def __init__(self, seed: int = 0, deterministic: bool = False) -> None:
        # seed/deterministic kept for protocol-shape compat with other
        # paradigms' make_episode_policy(cfg, instance_id, deterministic).
        self.seed = int(seed)
        self.deterministic = bool(deterministic)

    def reset(self) -> None:
        """No-op — CFR traversal owns per-iteration state, not policy."""
        return None

    def act(self, obs: Any, mask: Any, provider: Any) -> tuple:
        """CFR collector bypasses EpisodeRunner — act SHALL NOT be called.

        Raises ``RuntimeError`` to make routing mistakes loud (per
        engineering style §2.5 — no defensive silent default)."""
        raise RuntimeError(
            'CFREpisodePolicy.act: CFR paradigm does not rollout episodes — '
            'OS-MCCFR traversal is driven by CFRTraversalCollector directly. '
            'If you reached this, something routed a CFR run through '
            'EpisodeRunner; check Collector.collect path.'
        )

    def finalize_episode(self, transitions: list, winner: int, acting_player: int = 0) -> list:
        """No-op — traversal records cf-reach-weighted samples directly
        into reservoirs at recursion time; there is no per-episode
        backfill phase (spec C1.3)."""
        raise RuntimeError(
            'CFREpisodePolicy.finalize_episode: CFR paradigm does not '
            'rollout episodes — traversal records samples inline.'
        )
