"""CFR paradigm adapter — implements core.protocols.Paradigm.

Bridges the unified pipeline driver (training.core.pipeline.run_pipeline)
to the CFR implementation now flat under this package (post
core-network-generic-promotion Phase 2D, prev nested at .legacy/ subdir).
Frozen-research tier — new CFR runs SHALL NOT launch without OpenSpec
change unfreezing (paradigm-cfr/spec.md C6.3).

Adapter exists for r008 reproducibility (C6.2 — SUPERSEDED by
core-network-generic-promotion, ckpt schema obsolete; training path still
runnable from scratch). The serial CFRTrainer entry point (train.py) remains
functional; the async mp path is now ``CFRAsyncCollector`` driven through the
unified pipeline (I31 #88 CFR mp-pool unification).
"""

# Top-level Paradigm protocol
from training.paradigms.cfr._async import CFRAsyncCollector
from training.paradigms.cfr.collector import CFRTraversalCollector
from training.paradigms.cfr.paradigm import CFRParadigm

# Re-exports — preserve previous `from training.paradigms.cfr import X` import
# pattern that downstream tests + tooling depend on. After Phase 2D flatten,
# these moved out of cfr/legacy/network/ to cfr/{strategy_net,advantage_net}.py
# and cfr/fit_steps.py — re-export here to maintain API.
from training.paradigms.cfr.advantage_net import AdvantageNet, regret_to_policy
from training.paradigms.cfr.strategy_net import CFRNetConfig, CFRStrategyNet

__all__ = [
    'CFRParadigm',
    'CFRTraversalCollector',
    'CFRAsyncCollector',
    'CFRNetConfig',
    'CFRStrategyNet',
    'AdvantageNet',
    'regret_to_policy',
]
