"""PPOParadigmConfig — read from cfg.paradigm dict in TOML.

Driver receives ``TrainingConfig`` with `cfg.paradigm: dict` (paradigm-
specific schema). PPO adapter parses that dict into this frozen
dataclass for typed access. Spec ref: paradigm-ppo/spec.md P1-P6.

Carries the PPO-loss / rollout / network hparams the new pipeline
driver consumes (driver owns artifacts / ckpt cadence / total_frames
via cfg.checkpoint + cfg.meta). Env / scenario fields move to
cfg.scenario (driver-owned). Paradigm-local hparams stay here.

post ``ppo-cfg-shape-alignment`` (#7): ``PPOAgentShapeCfg = ObsShape``
alias (5/5 paradigm cfg dataclass 对称, CC-206 closure)。Fields delivered
by ``make_ppo_default_shape()`` factory (core/cfg/factories.py) +
``build_shape_from_toml`` merge per #5 hybrid TOML structure。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from training.core.cfg import (
    ObsShape,
    ParadigmConfigBase,
    build_shape_from_toml,
    make_ppo_default_shape,
)


# Backward-compat alias (cfg-schema-unification CC-202 pattern, extended to
# PPO in ppo-cfg-shape-alignment #7): existing imports
# `from training.paradigms.ppo.config import PPOAgentShapeCfg` resolve to the
# shared ObsShape dataclass. Field set unchanged (7 fields, already aligned
# post #4 ppo-structural-backbone-migration).
PPOAgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204 pattern).
_PPO_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class PPORolloutCfg:
    """[paradigm.rollout] section. PPO on-policy rollout cadence."""

    n_games_per_iter: int = 32
    max_steps_per_game: int = 200
    # Opponent for P1 during training rollouts. 'self' = classic self-
    # play; 'random' / 'F{i}-D{j}' / comma-separated mixes = asymmetric.
    # Detailed semantics: training/paradigms/ppo/collector.py docstring.
    rollout_opponent: str = 'self'


@dataclass(frozen=True)
class PPOParadigmConfig(ParadigmConfigBase):
    """Top-level PPO paradigm cfg. Default values preserve the retired
    PPO legacy stack's PPO-loss + rollout subset (FU-W4-PPO retire).

    Frozen tier (per P6.1) — new PPO production run SHALL NOT be launched
    without OpenSpec change unfreezing tier (P6.3)。

    cfg-schema-unification + ppo-cfg-shape-alignment (#7) closure:
    - inherits ParadigmConfigBase (version + paradigm metadata, N2)
    - agent: ObsShape via make_ppo_default_shape factory (N1.2, 5/5 paradigm 对称)
    - PPOAgentShapeCfg = ObsShape backward-compat alias (CC-202 pattern)
    """

    paradigm: str = 'ppo'

    # --- PPO loss hparams (P2) ---
    gamma: float = 0.99  # P1.3 — PPO sticks with γ=0.99 (AZ/DMC use 1.0)
    gae_lambda: float = 0.95  # P1.1 — GAE λ default
    clip_epsilon: float = 0.2  # P2.1 — clip ε default
    value_coef: float = 0.5  # P2.3 — value loss coef
    entropy_coef: float = 0.01  # P2.3 — entropy bonus coef
    lr: float = 3.0e-4
    max_grad_norm: float = 0.5

    # --- PPO update cadence (within one outer iter) ---
    n_epochs: int = 4  # PPO update epochs per rollout iter (P4 buffer reused)
    minibatch_size: int = 256

    # --- Buffer ---
    # P4.2: capacity = rollout_horizon × vec_env_size; for GICG (variable
    # episode length) we cap by upper bound (n_games × max_steps × 2 sides).
    buffer_cap: int = 50_000

    # --- Scheduling ---
    total_iterations: int = 1000  # outer rollout iters (legacy n_iterations)
    batch_size: int = 256  # minibatch size for protocol StepPlan.batch_size

    # --- Component config — paradigm-local ObsShape (N1.2, #7 closure) ---
    agent: ObsShape = field(default_factory=make_ppo_default_shape)
    rollout: PPORolloutCfg = field(default_factory=PPORolloutCfg)

    # --- Reward shaping forwarded to env (PPO uses dense shaping by D2) ---
    reward_shaping: dict = field(
        default_factory=lambda: {
            'hp_delta': 1.0,
            'hp_taken_penalty': 1.1,
            'terminal_win': 60.0,
            'terminal_loss': 60.0,
        }
    )

    @classmethod
    def from_dict(cls, d: dict) -> 'PPOParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Validation delegated to
        ``ParadigmConfigBase.from_dict_strict`` (W1-T3)."""
        return cls.from_dict_strict(
            d,
            paradigm_name='ppo',
            supported_versions=_PPO_SUPPORTED_VERSIONS,
            sub_section_factories={
                'agent': lambda dd: build_shape_from_toml(dd, make_ppo_default_shape),
                'rollout': lambda dd: PPORolloutCfg(**dd),
            },
        )
