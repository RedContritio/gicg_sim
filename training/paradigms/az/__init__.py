"""AZ paradigm adapter — implements core.protocols.Paradigm.

Self-contained adapter package: all AZ implementation modules
(``network``, ``mcts``, ``selfplay``, ``buffer``, ``train_step``,
``train_az``, ``inference_pool``, ``inference_worker``, ``determinize``,
``arena``, ``config``, ``config_loader``) live at this package
top-level. The pre-rewrite ``legacy/`` subdir has been git-removed
(az-paradigm-rewrite Phase 5, 2026-05-16). ``python -m tools.run`` is the
sole entry; the unified pipeline driver
(``training.core.pipeline.run_pipeline``) drives this adapter through
the ``core.protocols.Paradigm`` interface.

Spec ref: ``openspec/specs/paradigm-az/spec.md`` A1-A6."""

from training.paradigms.az.paradigm import AZParadigm

__all__ = ['AZParadigm']
