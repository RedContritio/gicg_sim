"""BCParadigmConfig — read from cfg.paradigm dict in TOML.

Driver receives ``TrainingConfig`` with `cfg.paradigm: dict` (paradigm-
specific schema). BC adapter parses that dict into this frozen
dataclass for typed access. Spec ref: paradigm-bc/spec.md BC1-BC6 +
config-schema/spec.md § 7 (cfg-schema-unification N1-N3)。

BC-specific fields focus on static dataset training:
 - dataset_path → YAML / NPZ expert replay path
 - loss_kind → "ce" (hard target) vs "kl" (soft teacher target);default "ce"
 - n_epochs → outer iter count;each iter = 1 dataset epoch
 - value_coef → MSE value loss weight(BC4.1: 0.0 disables value head training)

No env episode loop — buffer_cap = dataset_size,batch_size 沿 bc/legacy/bc_train.py。

cfg-schema-unification:
- inherits ParadigmConfigBase (version + paradigm metadata, N2)
- `agent: ObsShape` paradigm-local field via factory (N1.2)
- AgentShapeCfg = ObsShape alias preserves bc/network.py:21 import (CC-202)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from training.core.cfg import ObsShape, ParadigmConfigBase, build_shape_from_toml, make_bc_default_shape


# Backward-compat alias (CC-202): preserves `bc/network.py:21` import + tests.
AgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204).
_BC_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class BCParadigmConfig(ParadigmConfigBase):
    """Top-level BC paradigm cfg. Defaults reflect bc/legacy/bc_train.py legacy
    smoke preset; production runs override via cfg.paradigm dict.

    NB: ``buffer_cap`` defaults to a large soft-cap; the DatasetCollector
    sizes itself from the actual dataset on load.
    """

    paradigm: str = 'bc'

    # Dataset (BC1.1)
    dataset_path: str = ''  # must be set;empty triggers raise in collector
    held_out_frac: float = 0.1

    # Loss (BC2.1 / BC2.3)
    loss_kind: str = 'ce'  # 'ce' (hard target) | 'kl' (soft teacher target)
    value_coef: float = 0.0  # BC4.1 — value head not trained by default

    # Optimizer
    lr: float = 1e-4
    weight_decay: float = 0.0
    batch_size: int = 256
    grad_clip: float = 1.0

    # Schedule
    n_epochs: int = 60
    buffer_cap: int = 1_000_000  # soft cap;dataset can be smaller

    # Component config — paradigm-local ObsShape (N1.2)
    agent: ObsShape = field(default_factory=make_bc_default_shape)

    @classmethod
    def from_dict(cls, d: dict) -> 'BCParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Validation delegated to
        ``ParadigmConfigBase.from_dict_strict`` (W1-T3); BC-specific
        post-validation (loss_kind ∈ {'ce','kl'} per BC2.1) runs after."""
        cfg = cls.from_dict_strict(
            d,
            paradigm_name='bc',
            supported_versions=_BC_SUPPORTED_VERSIONS,
            sub_section_factories={
                'agent': lambda dd: build_shape_from_toml(dd, make_bc_default_shape),
            },
        )
        if cfg.loss_kind not in ('ce', 'kl'):
            raise ValueError(f'BCParadigmConfig: loss_kind must be "ce" or "kl", got {cfg.loss_kind!r}')
        return cfg
