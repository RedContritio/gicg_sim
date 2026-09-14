"""DMC paradigm adapter — implements core.protocols.Paradigm.

Bridges the unified pipeline driver (``training.core.pipeline.run_pipeline``)
to the DMC modules in this package. The former ``tools/dmc_train.py`` and
``training.dmc`` paths have been removed; ``tools.runs.train`` is the current
training entry."""

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
