"""Paradigm-agnostic training interfaces and shared components.

OpenSpec ref: openspec/specs/training-architecture/spec.md + ship-time
change ``unified-training-pipeline`` (Phase 3 first half).

The package exposes the 6 Protocol contracts every paradigm SHALL
implement plus the shared Driver / Provider / EpisodeRunner /
NetworkProvider / Buffer / OpponentRegistry abstractions. Concrete
paradigm adapters live in ``training/paradigms/<name>/`` and plug into
this scaffold through the protocol layer.

"""

from training.core.protocols import (
    Batch,
    Buffer,
    Collector,
    CollectorOutput,
    EpisodePolicy,
    EpisodeSpec,
    EpisodeRecord,
    LossComputer,
    LossResult,
    NetworkProvider,
    Paradigm,
    PipelineState,
    StepPlan,
    Transition,
)

__all__ = [
    'Batch',
    'Buffer',
    'Collector',
    'CollectorOutput',
    'EpisodePolicy',
    'EpisodeSpec',
    'EpisodeRecord',
    'LossComputer',
    'LossResult',
    'NetworkProvider',
    'Paradigm',
    'PipelineState',
    'StepPlan',
    'Transition',
]
