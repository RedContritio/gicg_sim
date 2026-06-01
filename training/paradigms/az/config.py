"""AZ adapter configuration — unified pipeline driver cfg.

``AZParadigmConfig`` + sub-cfgs (``AgentShapeCfg`` / ``MCTSCfg`` /
``TrainStepCfg``) — frozen dataclasses consumed by the unified pipeline
driver via ``cfg.paradigm`` dict (spec ref: paradigm-az/spec.md A1-A6).

The legacy ``AZConfig`` + preset builders (``smoke_config`` /
``fixed_1v1_config`` / ``random_1v1_config``) were git-removed in the
I31 AZ mp-pool unification (方向 C) along with the ``train_az`` loop
that consumed them. Production runs entirely through the unified
pipeline; cfg now comes from TOML via ``core.config.loader.load_cfg``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from training.core.cfg import ObsShape, ParadigmConfigBase, build_shape_from_toml, make_az_default_shape

__all__ = [
    'AZParadigmConfig',
    'AgentShapeCfg',
    'MCTSCfg',
    'TrainStepCfg',
]


# ---------------------------------------------------------------------------
# Unified pipeline driver cfg (frozen dataclasses from TOML dict)
# ---------------------------------------------------------------------------

# Backward-compat alias (cfg-schema-unification CC-202): existing imports
# `from training.paradigms.az.config import AgentShapeCfg` resolve to the
# shared ObsShape dataclass. Field set unchanged (7 fields).
AgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204). Future bump = explicit
# OpenSpec change synchronously updating this set + dataclass default.
_AZ_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class MCTSCfg:
    """[paradigm.mcts] section — knobs for IS-MCTS selfplay search.

    Mirrors ``training.paradigms.az.mcts.MCTSConfig`` field-for-field so
    we can build one directly without translation."""

    n_rollouts: int = 200
    c_puct: float = 1.4
    dirichlet_alpha: float = 0.3
    dirichlet_eps: float = 0.25
    temperature: float = 1.0
    temperature_switch_step: int = 15
    max_rollout_depth: int = 400
    parallel_rollouts: int = 1
    value_mix_lambda: float = 1.0
    prior_mix_lambda: float = 1.0
    lambda_anneal_games: int = 0
    lambda_start: float = 0.0
    lambda_end: float = 0.8
    profile: bool = True
    backend: str = 'python'


@dataclass(frozen=True)
class TrainStepCfg:
    """[paradigm.train] section — algorithm-side training knobs.

    Mirrors ``training.paradigms.az.train_step.TrainStepConfig``."""

    l2_coef: float = 1e-4
    max_grad_norm: float = 1.0
    value_target_source: str = 'z'  # 'z' | 'mcts_value' | 'mixed'
    value_mix_lambda: float = 0.5
    entropy_coef: float = 0.0
    delta_aux_coef: float = 0.1


@dataclass(frozen=True)
class AZParadigmConfig(ParadigmConfigBase):
    """Top-level AZ paradigm cfg (cfg-schema-unification N2)."""

    paradigm: str = 'az'
    lr: float = 1e-3
    weight_decay: float = 0.0
    batch_size: int = 64
    buffer_cap: int = 200_000
    priority_weight: float = 3.0
    max_game_steps: int = 400
    total_games: int = 2000
    train_steps_per_game: int = 4
    sync_weights_every_train_steps: int = 0  # async weight republish cadence (0/1 = each train iter)
    min_buffer_before_train: int = 256
    init_from_ckpt: Optional[str] = None
    agent: ObsShape = field(default_factory=make_az_default_shape)
    mcts: MCTSCfg = field(default_factory=MCTSCfg)
    train: TrainStepCfg = field(default_factory=TrainStepCfg)

    @classmethod
    def from_dict(cls, d: dict) -> 'AZParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Validation delegated to
        ``ParadigmConfigBase.from_dict_strict`` (W1-T3 — unknown-key,
        version, paradigm-name template shared across 5 paradigm)."""
        return cls.from_dict_strict(
            d,
            paradigm_name='az',
            supported_versions=_AZ_SUPPORTED_VERSIONS,
            sub_section_factories={
                'agent': lambda dd: build_shape_from_toml(dd, make_az_default_shape),
                'mcts': lambda dd: MCTSCfg(**dd),
                'train': lambda dd: TrainStepCfg(**dd),
            },
        )
