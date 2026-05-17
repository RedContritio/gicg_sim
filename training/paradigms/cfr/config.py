"""CFRParadigmConfig — typed cfg.paradigm payload for CFR adapter.

Spec ref: paradigm-cfr/spec.md C1-C6 + config-schema/spec.md § 7
(cfg-schema-unification N1-N3)。

Frozen-research tier:
- C3.3 default capacities: advantage=200_000 / strategy=1_000_000
- C5.1 traversal collector (n_units = n_traversals per iter)
- C6 frozen-research — new run requires unfreeze change

Fields mirror the subset of `training.paradigms.cfr.train.CFRTrainConfig` that the
unified driver consumes; the driver itself owns ckpt cadence /
total_iterations / artifacts (cfg.checkpoint / cfg.meta) so paradigm-local
fields stay here. Per-component nested shapes (network / traversal) get
their own typed dataclasses to keep `from_dict` strict-key-validated.

cfg-schema-unification:
- inherits ParadigmConfigBase (version + paradigm metadata, N2)
- `agent: ObsShape` paradigm-local field via factory (N1.2)
- CFRAgentShapeCfg = ObsShape alias preserves test_cfr_paradigm.py
  isinstance check + import (CC-202)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from training.core.cfg import ObsShape, ParadigmConfigBase, build_shape_from_toml, make_cfr_default_shape


# Backward-compat alias (CC-202): test_cfr_paradigm.py isinstance + import.
CFRAgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204).
_CFR_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class CFRTraversalCfg:
    """OS-MCCFR traversal hyperparameters.

    Mirrors `training.paradigms.cfr.traversal.config.TraversalConfig` field names
    1:1 (sampling_mode / epsilon / max_game_steps / importance_weight_max)
    so the adapter can build one without translation. Adds
    ``traverser_alternation`` (paradigm-layer choice, not traverser
    internal).
    """

    sampling_mode: str = 'os'  # 'os' = outcome-sampling MCCFR (spec C1.1)
    epsilon: float = 0.1
    max_game_steps: int = 400
    importance_weight_max: float = 100.0
    traverser_alternation: str = 'alternate'  # 'alternate' or 'random'


@dataclass(frozen=True)
class CFRParadigmConfig(ParadigmConfigBase):
    """Top-level CFR paradigm cfg. Defaults are smoke-sized."""

    paradigm: str = 'cfr'

    # Algorithm hparams (C2)
    advantage_lr: float = 1e-3
    strategy_lr: float = 1e-3
    grad_clip_max_norm: float = 1.0
    advantage_reset_each_iter: bool = False
    value_loss_alpha: float = 1.0

    # Fit cadence
    advantage_fit_steps_per_iter: int = 32
    strategy_fit_every: int = 4
    strategy_fit_steps: int = 64
    fit_batch_size: int = 128

    # Buffer (C3.3 — frozen-research defaults reduced for smoke; production
    # raises via cfg override).
    advantage_buffer_capacity: int = 100_000
    strategy_buffer_capacity: int = 200_000
    value_buffer_capacity: int = 100_000

    # Scheduling (iter-based per C5.1 — n_traversals per iter)
    n_iterations: int = 100
    traversals_per_iteration: int = 64

    # Tier (C6.1 — frozen-research; runtime guard in paradigm.make_network).
    tier: str = 'frozen-research'

    # Component config — paradigm-local ObsShape (N1.2)
    agent: ObsShape = field(default_factory=make_cfr_default_shape)
    traversal: CFRTraversalCfg = field(default_factory=CFRTraversalCfg)

    @classmethod
    def from_dict(cls, d: dict) -> 'CFRParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Unknown keys → raise.

        Additional validations (cfg-schema-unification N3):
        - `version` ∈ _CFR_SUPPORTED_VERSIONS;若缺省默认 '1.0.0'
        - `paradigm` 字段值若提供必须 == 'cfr'(CC-205)
        """
        allowed = set(cls.__dataclass_fields__.keys())
        unknown = set(d.keys()) - allowed
        if unknown:
            raise ValueError(
                f'CFRParadigmConfig.from_dict: unknown paradigm key(s) {sorted(unknown)} (allowed: {sorted(allowed)})'
            )
        version = d.get('version', '1.0.0')
        if version not in _CFR_SUPPORTED_VERSIONS:
            raise ValueError(
                f'CFRParadigmConfig: unsupported version {version!r} (supported: {sorted(_CFR_SUPPORTED_VERSIONS)})'
            )
        paradigm_val = d.get('paradigm', 'cfr')
        if paradigm_val != 'cfr':
            raise ValueError(f'CFRParadigmConfig: paradigm mismatch: expected cfr, got {paradigm_val!r}')
        agent_d = d.get('agent', {})
        trav_d = d.get('traversal', {})
        kwargs: dict = {k: v for k, v in d.items() if k not in ('agent', 'traversal')}
        if isinstance(agent_d, dict):
            kwargs['agent'] = build_shape_from_toml(agent_d, make_cfr_default_shape)
        if isinstance(trav_d, dict):
            kwargs['traversal'] = CFRTraversalCfg(**trav_d)
        return cls(**kwargs)
