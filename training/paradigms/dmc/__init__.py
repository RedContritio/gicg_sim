"""DMC paradigm adapter — implements core.protocols.Paradigm.

Bridges the unified pipeline driver (training.core.pipeline.run_pipeline)
to the existing DMC implementation (training.dmc.{agent,replay,loss}).
The old single-entry `tools/dmc_train.py → training.dmc.train.run` remains
working as a fallback (dual-path until P5 mv consolidation)."""

from training.paradigms.dmc.collector import (
    DMCAsyncCollector,
    DMCMultiProcessCollector,
    DMCSerialCollector,
)
from training.paradigms.dmc.paradigm import DMCParadigm

__all__ = [
    'DMCParadigm',
    'DMCSerialCollector',
    'DMCMultiProcessCollector',
    'DMCAsyncCollector',
]
