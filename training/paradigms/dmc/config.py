"""DMCParadigmConfig — read from cfg.paradigm dict in TOML.

Driver receives ``TrainingConfig`` with `cfg.paradigm: dict` (paradigm-
specific schema). DMC adapter parses that dict into this frozen
dataclass for typed access. Spec ref: paradigm-dmc/spec.md D1-D7 +
config-schema/spec.md § 7 (cfg-schema-unification N1-N3)。

Fields mirror the legacy `training.dmc.config.DmcConfig` subset that
the new pipeline driver consumes — NOT a 1:1 port because driver owns
artifacts / ckpt cadence / total_frames already (cfg.checkpoint /
cfg.meta). Paradigm-local fields stay here.

cfg-schema-unification:
- inherits ParadigmConfigBase (version + paradigm metadata, N2)
- `agent: ObsShape` paradigm-local field via factory (N1.2)
- AgentShapeCfg = ObsShape alias preserves test_dmc_paradigm.py
  isinstance check + dmc/paradigm.py import (CC-202)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from training.core.cfg import ObsShape, ParadigmConfigBase, build_shape_from_toml, make_dmc_default_shape


# Backward-compat alias (CC-202).
AgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204).
_DMC_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class OpponentMixCfg:
    """[paradigm.opponent_mix] section. Must sum to 1.0."""

    random: float = 0.40
    f1d2: float = 0.30
    f1d4: float = 0.00
    historical: float = 0.30
    ring_size: int = 5

    def __post_init__(self) -> None:
        s = self.random + self.f1d2 + self.f1d4 + self.historical
        if abs(s - 1.0) > 1e-6:
            raise ValueError(
                f'OpponentMixCfg: weights must sum to 1.0 (got {s}: random={self.random} '
                f'f1d2={self.f1d2} f1d4={self.f1d4} historical={self.historical})'
            )


@dataclass(frozen=True)
class DMCParadigmConfig(ParadigmConfigBase):
    """Top-level DMC paradigm cfg. Default values match
    `configs/dmc_stage3_smoke.toml`'s legacy DmcConfig smoke preset."""

    paradigm: str = 'dmc'

    # Algorithm hparams (spec D2-D3, D6)
    epsilon: float = 0.05  # D3.2 ε-greedy actor
    gamma: float = 1.0  # D1.2 MC undiscounted
    lr: float = 1e-4
    weight_decay: float = 0.0
    batch_size: int = 16
    max_grad_norm: float = 5.0  # spec D-implicit (review C.9)

    # Buffer (D4.3)
    buffer_cap: int = 5000

    # Episode bound (engine-level)
    max_game_steps: int = 400

    # Scheduling
    total_frames: int = 5000  # smoke default; production overrides
    train_ratio: int = 4  # n_drained × train_ratio per outer iter
    weight_sync_every_steps: int = 0  # 0 = sync each iter (serial-mode); >0 = every-N iter

    # Component config — paradigm-local ObsShape (N1.2)
    agent: ObsShape = field(default_factory=make_dmc_default_shape)
    opponent_mix: OpponentMixCfg = field(default_factory=OpponentMixCfg)

    # Eval cadence (legacy DMC eval block — wraps existing PeriodicEvaluator
    # if cfg.eval.inference is None; otherwise driver's core/eval path)
    eval_interval_episodes: int = 30
    eval_n_scenarios: int = 8
    eval_baselines: tuple = ('F1-D2',)

    # CPU affinity hints for the DMC training pipeline. Lists of logical
    # CPU IDs, e.g. [0,1,...,15] for X3D CCD0. Silently skipped on
    # platforms without cpu_affinity support (macOS) — the field
    # declarations stand as portable cfg shape, the runtime apply site
    # decides what's actionable per host.
    # - ``cpu_affinity_actors``: pinned in each spawned actor process via
    #   ``training/core/actor/actor_process.py:actor_main`` →
    #   ``harden_child_env(affinity=...)``.
    # - ``cpu_affinity_learner``: pinned in the main training process via
    #   ``tools/runs/_train/dispatch.py:_apply_learner_affinity`` before
    #   the paradigm pipeline starts.
    # - ``cpu_affinity_eval``: DOCUMENTATION-ONLY here — the runtime
    #   actor for evals is the separate ``tools/remote/eval_service.py``
    #   process, which cannot read DMCParadigmConfig at runtime. The
    #   intent is to feed this value into an eval_service ``--cpu-affinity``
    #   CLI flag in a follow-up task; for now this field exists so the
    #   canonical X3D core-assignment intent lives next to its siblings.
    cpu_affinity_actors: Optional[list[int]] = None
    cpu_affinity_learner: Optional[list[int]] = None
    cpu_affinity_eval: Optional[list[int]] = None

    # Inference acceleration mode for the actor's forward path
    # (DMCInferenceNet wired through LocalNetworkProvider in
    # DMCSerialCollector._ensure_dmc_provider). One of:
    #
    # - 'none' (default): bypass; run network as-is.
    # - 'trace': lazy first-forward torch.jit.trace; invalidated on
    #   weight update.
    # - 'compile': torch.compile(net, mode='reduce-overhead',
    #   dynamic=True) once at provider ctor. dynamic=True is critical
    #   because DMC obs has variable n_legal_actions per turn — without
    #   it cache thrash would make compile slower than no compile.
    #
    # Wiring gap: training/core/actor/provider_factory.build_network_provider
    # does not currently plumb this field, and InferenceCfg's R7
    # contract fixes its field set at 4. Paradigms read this field
    # directly when constructing LocalNetworkProvider (see
    # DMCSerialCollector._ensure_dmc_provider).
    inference_acceleration: str = 'none'

    @classmethod
    def from_dict(cls, d: dict) -> 'DMCParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Unknown keys → raise (CS4).

        Additional validations (cfg-schema-unification N3):
        - `version` ∈ _DMC_SUPPORTED_VERSIONS;若缺省默认 '1.0.0'
        - `paradigm` 字段值若提供必须 == 'dmc'(CC-205)
        - `inference_acceleration` ∈ {'none','trace','compile'}
        - `use_jit_trace` (deprecated alias): if True → converted to
          `inference_acceleration='trace'` with a DeprecationWarning.
        """
        # Translate deprecated `use_jit_trace` alias before the unknown-
        # key check so the field name stays out of the allowed set.
        d = dict(d)  # avoid mutating caller's dict
        if 'use_jit_trace' in d:
            import warnings as _warnings

            legacy_val = d.pop('use_jit_trace')
            if legacy_val:
                if d.get('inference_acceleration', 'none') != 'none':
                    raise ValueError(
                        'DMCParadigmConfig: cannot set both use_jit_trace=True and '
                        f'inference_acceleration={d["inference_acceleration"]!r}; '
                        "use inference_acceleration='trace' only."
                    )
                _warnings.warn(
                    "DMCParadigmConfig: use_jit_trace is deprecated, use inference_acceleration='trace' instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                d['inference_acceleration'] = 'trace'
        allowed = set(cls.__dataclass_fields__.keys())
        unknown = set(d.keys()) - allowed
        if unknown:
            raise ValueError(
                f'DMCParadigmConfig.from_dict: unknown paradigm key(s) {sorted(unknown)} (allowed: {sorted(allowed)})'
            )
        version = d.get('version', '1.0.0')
        if version not in _DMC_SUPPORTED_VERSIONS:
            raise ValueError(
                f'DMCParadigmConfig: unsupported version {version!r} (supported: {sorted(_DMC_SUPPORTED_VERSIONS)})'
            )
        paradigm_val = d.get('paradigm', 'dmc')
        if paradigm_val != 'dmc':
            raise ValueError(f'DMCParadigmConfig: paradigm mismatch: expected dmc, got {paradigm_val!r}')
        accel = d.get('inference_acceleration', 'none')
        if accel not in ('none', 'trace', 'compile'):
            raise ValueError(
                f"DMCParadigmConfig: inference_acceleration must be one of ['none','trace','compile'], got {accel!r}"
            )
        agent_d = d.get('agent', {})
        opp_d = d.get('opponent_mix', {})
        kwargs: dict = {k: v for k, v in d.items() if k not in ('agent', 'opponent_mix')}
        if isinstance(agent_d, dict):
            kwargs['agent'] = build_shape_from_toml(agent_d, make_dmc_default_shape)
        if isinstance(opp_d, dict):
            kwargs['opponent_mix'] = OpponentMixCfg(**opp_d)
        # eval_baselines may come from TOML as list; coerce to tuple
        if 'eval_baselines' in kwargs and isinstance(kwargs['eval_baselines'], list):
            kwargs['eval_baselines'] = tuple(kwargs['eval_baselines'])
        return cls(**kwargs)
