"""AZ paradigm adapter — implements core.protocols.Paradigm.

Self-contained adapter package: all AZ implementation modules
(``network``, ``mcts``, ``selfplay``, ``determinize``, ``buffer``,
``train_step``, ``collector``, ``mp_factories``, ``pool_spec``,
``config``) live at this package top-level. The legacy mp stack
(``train_az`` / ``train_loop`` / ``inference_pool`` / ``inference_worker``
/ ``arena`` / ``config_loader``) was git-removed in the I31 AZ mp-pool
unification (方向 C, 2026-06-01) — production runs entirely through the
unified pipeline driver (``training.core.pipeline.run_pipeline``) via the
``core.protocols.Paradigm`` interface, with ``python -m tools.runs.train``
as the sole entry.

Spec ref: ``openspec/specs/paradigm-az/spec.md`` A1-A6."""

from training.paradigms.az.paradigm import AZParadigm

__all__ = ['AZParadigm']
