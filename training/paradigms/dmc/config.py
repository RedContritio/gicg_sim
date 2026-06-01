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
    # minimax_node_budget — F1-D4 greedy opp 跨整个 select_action call 的 snapshot/step
    # 总数上限。 None (default) = 无 cap (production 历史行为,D4 完整跑 ~5-15s/episode)。
    # 设显式值 (典型 4000) 让 Python `_score_best_response` 与 Go
    # `gicg_actor/dmc/greedy_player.go` MinimaxNodeBudget 行为对齐 — cross-language
    # fair bench 测纯 pipeline overhead 而非 algorithm-shortcut asymmetry。 C2 fix
    # (2026-05-25):pre-C2 Go 硬码 const 4000 而 Python 无 cap = 跑不同 algo,3.66x
    # ratio 部分来自此 asymmetry;C2 后两侧都 cfg-driven,bench cfg explicit 对齐。
    minimax_node_budget: Optional[int] = None

    def __post_init__(self) -> None:
        s = self.random + self.f1d2 + self.f1d4 + self.historical
        if abs(s - 1.0) > 1e-6:
            raise ValueError(
                f'OpponentMixCfg: weights must sum to 1.0 (got {s}: random={self.random} '
                f'f1d2={self.f1d2} f1d4={self.f1d4} historical={self.historical})'
            )
        if self.minimax_node_budget is not None and self.minimax_node_budget <= 0:
            raise ValueError(f'OpponentMixCfg: minimax_node_budget must be > 0 or None, got {self.minimax_node_budget}')


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
    sync_weights_every_train_steps: int = 0  # async weight republish cadence (0/1 = each train iter); >0 = every-N

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
    #   actor for evals is the separate ``tools/eval/eval_service.py``
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

    # Dotted-module paths consumed by the mp actor bootstrap. Resolved
    # inside spawned children by ``training.core.actor.actor_process.
    # resolve_builder``. Only required when ``cfg.pipeline.mode='async'``;
    # serial mode never reads them. The new wire path (P2-PoC E target)
    # routes ``DMCMultiProcessCollector._bootstrap`` to factories under
    # ``training.paradigms.dmc.mp_factories``; legacy resolver path
    # (``training.paradigms.dmc.collector._dmc_build_*``) still consumes
    # these fields via cfg.paradigm dict for backward compat.
    mp_env_factory_path: Optional[str] = None
    mp_opp_registry_path: Optional[str] = None
    mp_provider_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> 'DMCParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Validation delegated to
        ``ParadigmConfigBase.from_dict_strict`` (W1-T3); DMC-specific
        pre-processing (use_jit_trace deprecation translation,
        eval_baselines list→tuple coerce) + post-validation
        (inference_acceleration enum) wraps it.
        """
        # Pre-process: translate deprecated ``use_jit_trace`` alias before the
        # unknown-key check so the field name stays out of the allowed set.
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

        # Pre-process: eval_baselines may come from TOML as list; coerce to tuple
        # before dataclass construction (dataclass field is declared tuple).
        if 'eval_baselines' in d and isinstance(d['eval_baselines'], list):
            d['eval_baselines'] = tuple(d['eval_baselines'])

        cfg = cls.from_dict_strict(
            d,
            paradigm_name='dmc',
            supported_versions=_DMC_SUPPORTED_VERSIONS,
            sub_section_factories={
                'agent': lambda dd: build_shape_from_toml(dd, make_dmc_default_shape),
                'opponent_mix': lambda dd: OpponentMixCfg(**dd),
            },
        )

        # Post-validate inference_acceleration enum (subset of strings).
        if cfg.inference_acceleration not in ('none', 'trace', 'compile'):
            raise ValueError(
                'DMCParadigmConfig: inference_acceleration must be one of '
                f"['none','trace','compile'], got {cfg.inference_acceleration!r}"
            )
        return cfg
