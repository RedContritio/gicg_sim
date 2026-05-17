"""training.core.cfg — paradigm-shared config primitives.

Provides:
- ``ObsShape``: observation shape dataclass shared across 5 paradigm
  (AZ / BC / CFR / DMC / PPO) via paradigm-local ``agent: ObsShape`` field.
  PPO added post ``ppo-cfg-shape-alignment`` (#7) following structural
  backbone migration (#4).
- ``ParadigmConfigBase``: base for paradigm-specific config dataclass
  (version + paradigm metadata; subclass provides shape via ``agent``
  field per CC-201/203).
- ``make_{az,bc,cfr,dmc,ppo}_default_shape``: per-paradigm ObsShape factory
  functions returning paradigm historical defaults (d_model + n_cross_layers
  diverge; base shape fields shared).

Spec: ``openspec/specs/config-schema/spec.md`` § 7 N1 (ObsShape SSOT) +
N2 (ParadigmConfigBase compose) + N3 (version field).
"""

from training.core.cfg.base import ParadigmConfigBase
from training.core.cfg.factories import (
    build_shape_from_toml,
    make_az_default_shape,
    make_bc_default_shape,
    make_cfr_default_shape,
    make_dmc_default_shape,
    make_ppo_default_shape,
)
from training.core.cfg.loader import load_paradigm_cfg
from training.core.cfg.shape import ObsShape

__all__ = [
    'ObsShape',
    'ParadigmConfigBase',
    'build_shape_from_toml',
    'load_paradigm_cfg',
    'make_az_default_shape',
    'make_bc_default_shape',
    'make_cfr_default_shape',
    'make_dmc_default_shape',
    'make_ppo_default_shape',
]
