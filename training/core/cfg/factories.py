"""Paradigm-specific ObsShape factory functions.

Each factory returns ``ObsShape`` with paradigm 历史 production
default values (preserved from pre-unification AgentShapeCfg
defaults). 5 paradigm × 1 factory each — PPO added post
``ppo-cfg-shape-alignment`` (#7) since ``ppo-structural-backbone-migration``
(#4) switched PPO to structural backbone making ObsShape applicable。

Spec ref: config-schema/spec.md § 7 N1.2 (factory composition).
"""

from __future__ import annotations

from training.core.cfg.shape import ObsShape


# Shared base shape fields — engine-determined token / counter / hook
# capacity (per ADR-0019 + #152 mirror fix). All 5 paradigm share these;
# only d_model / n_cross_layers vary per paradigm historical default.
_BASE_SHAPE_FIELDS = dict(
    n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,  # 1832
    n_hooks=900,
    max_ops_per_hook=128,  # IR-4: matches engine.ObsMaxOpsPerHook (was 120 in token era)
    max_actions=2048,
    dropout=0.0,
)


def make_az_default_shape() -> ObsShape:
    """AZ historical default — d_model=128 / n_cross_layers=2.

    Matches pre-unification ``training.paradigms.az.config.AgentShapeCfg``
    defaults (fixed_1v1_config production preset)."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=128, n_cross_layers=2)


def make_bc_default_shape() -> ObsShape:
    """BC historical default — d_model=32 / n_cross_layers=1.

    Matches pre-unification ``training.paradigms.bc.config.AgentShapeCfg``
    defaults (smoke / pre-train preset)."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=32, n_cross_layers=1)


def make_cfr_default_shape() -> ObsShape:
    """CFR historical default — d_model=64 / n_cross_layers=2.

    Matches pre-unification ``training.paradigms.cfr.config.CFRAgentShapeCfg``
    defaults (frozen-research tier)."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=64, n_cross_layers=2)


def make_dmc_default_shape() -> ObsShape:
    """DMC historical default — d_model=32 / n_cross_layers=1.

    Matches pre-unification ``training.paradigms.dmc.config.AgentShapeCfg``
    defaults (Stage 3 baseline preset)."""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=32, n_cross_layers=1)


def make_ppo_default_shape() -> ObsShape:
    """PPO structural default — d_model=128 / n_cross_layers=2.

    Post ``ppo-structural-backbone-migration`` (#4) PPO uses generic structural
    ActorCritic via ``make_actor_critic(head_kinds={'policy','value'},
    use_typed_damage=True)``. Field defaults align with AZ structural
    baseline (historical flat-MLP `d_model=256` retired in #4 alongside
    `_PPOMLPTrunk`)。Closes ``ppo-cfg-shape-alignment`` (#7) — completes 5/5
    paradigm cfg dataclass 对称 (CC-206 closure)。"""
    return ObsShape(**_BASE_SHAPE_FIELDS, d_model=128, n_cross_layers=2)


def build_shape_from_toml(d: dict, factory) -> ObsShape:
    """Merge toml-provided shape fields onto a paradigm factory default.

    Toml may omit any subset of ObsShape fields; missing ones fall back to
    ``factory()`` values. Empty dict → equivalent to factory call.
    Unknown ObsShape field → raise (strict per CS4).

    Used by 4 paradigm config.from_dict to construct ``agent: ObsShape``
    from `[paradigm.agent]` dict in toml.
    """
    if not d:
        return factory()
    base = factory()
    merged = {f: getattr(base, f) for f in base.__dataclass_fields__}
    for k, v in d.items():
        if k not in merged:
            raise ValueError(f'shape: unknown field {k!r} (allowed: {sorted(merged)})')
        merged[k] = v
    return ObsShape(**merged)
