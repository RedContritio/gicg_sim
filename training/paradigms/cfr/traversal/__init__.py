"""CFR traversal: outcome-sampling (OS) + external-sampling (ES) MCCFR.

Split into:
  encoding     — static + dynamic obs encoding helpers
  config       — TraversalConfig + _RecordedDecision + TraversalStats
  traverser    — TraverserBase with shared helpers
  os_sampling  — OSMixin (outcome sampling MCCFR)
  es_sampling  — ESMixin (external sampling MCCFR)

Final CFRTraverser = class(TraverserBase, OSMixin, ESMixin).
"""

from __future__ import annotations

from training.paradigms.cfr.traversal.config import (
    TraversalConfig,
    TraversalStats,
    _RecordedDecision,
)
from training.paradigms.cfr.traversal.es_sampling import ESMixin
from training.paradigms.cfr.traversal.os_sampling import OSMixin
from training.paradigms.cfr.traversal.traverser import TraverserBase


class CFRTraverser(TraverserBase, OSMixin, ESMixin):
    """Runs one outcome-sampling or external-sampling MCCFR traversal
    per call. ``config.sampling_mode`` ('os' | 'es') selects the
    mixin's ``traverse``. See module docstring on
    ``training.paradigms.cfr.traversal.os_sampling`` + ``.es_sampling``."""

    def traverse(self, env, traverser_player: int, iteration: int) -> TraversalStats:
        """Run one traversal. env must be freshly reset before this call."""
        stats = TraversalStats()

        # Static encoding (shared across both modes)
        static, gid_adv, gid_str, gid_val, adv_buffer = self._prepare_traversal(env, traverser_player)

        # Walk past PHASE_SELECT_ACTIVE
        while env._engine.phase == 1 and not env.done:
            env.step(0)

        if self.config.sampling_mode == 'es':
            return self._traverse_external_sampling(
                env,
                traverser_player,
                iteration,
                static,
                adv_buffer,
                gid_adv,
                gid_str,
                gid_val,
                stats,
            )
        if self.config.sampling_mode != 'os':
            raise ValueError(f"unknown sampling_mode {self.config.sampling_mode!r}; expected 'os' or 'es'")
        return self._traverse_outcome_sampling(
            env,
            traverser_player,
            iteration,
            static,
            adv_buffer,
            gid_adv,
            gid_str,
            gid_val,
            stats,
        )


__all__ = [
    'CFRTraverser',
    'TraversalConfig',
    'TraversalStats',
    '_RecordedDecision',
]
