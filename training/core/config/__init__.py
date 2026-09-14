"""TOML configuration, placement validation, and device/seed inheritance.

OpenSpec ref: ``openspec/specs/config-schema/spec.md`` (CS1-CS4 SHALL).
"""

from training.core.config.base import (
    EvalCfg,
    InferenceCfg,
    LearnerCfg,
    MetaCfg,
    PipelineCfg,
    RemoteInferenceCfg,
    ScenarioCfg,
    TrainingConfig,
)
from training.core.config.inheritance import (
    INHERITED_FIELDS,
    derive_seed,
    resolve_inheritance,
)
from training.core.config.loader import load_cfg
from training.core.config.schema import validate_schema

__all__ = [
    'EvalCfg',
    'InferenceCfg',
    'LearnerCfg',
    'MetaCfg',
    'PipelineCfg',
    'RemoteInferenceCfg',
    'ScenarioCfg',
    'TrainingConfig',
    'INHERITED_FIELDS',
    'derive_seed',
    'resolve_inheritance',
    'load_cfg',
    'validate_schema',
]
