"""Hybrid TOML structure loader helper.

Spec ref: config-schema/spec.md § 8 N6 (cfg-toml-restructure-paradigm-scoped
delta).

Extracts paradigm-scoped cfg from a hybrid TOML root dict shape:

    [shape]                          # 共享 obs schema (顶层) — optional
    n_counter_slots = ...
    d_model = ...

    [paradigm.<name>]                # paradigm 顶层 hparam
    lr = ...

    [paradigm.<name>.agent]          # paradigm sub-cfg, override [shape]
    d_model = ...                    # overrides [shape].d_model

    [paradigm.<name>.X]              # other sub-cfg (mcts/train/rollout/...)
    ...

Output is a flat dict suitable for ``<X>ParadigmConfig.from_dict()`` — same
shape as the legacy flat ``[paradigm]`` section, with ``agent`` sub-dict
merged from ``[shape]`` base + per-paradigm override (per CC-303 / CC-305).

Hard break (CC-301): legacy flat ``[paradigm]`` scalar fields (e.g.
``[paradigm] lr = 1e-3``) → raise pointing to hybrid structure. No silent
backward-compat shim.

Non-dispatched ``[paradigm.<wrong_name>]`` sections silently ignored
(CC-304) — enables single toml multi-paradigm reference cfgs.
"""

from __future__ import annotations


# Known paradigm dispatch keys — used to disambiguate legacy flat structure
# (scalar `lr=...` directly under [paradigm]) from a paradigm-named key
# whose value happens to be malformed (e.g. typo `[paradigm.az] = "x"`).
# Kept in sync with `core/config/base.py::PARADIGM_VALUES`.
_KNOWN_PARADIGM_NAMES = frozenset({'az', 'bc', 'cfr', 'dmc', 'ppo'})


def load_paradigm_cfg(toml_dict: dict, paradigm_name: str) -> dict:
    """Extract paradigm-scoped cfg from a hybrid TOML root dict.

    Args:
        toml_dict: full TOML root dict after inheritance, overrides, and
            top-level schema validation.
        paradigm_name: paradigm dispatch key (== ``cfg.meta.paradigm``).

    Returns:
        Flat dict for ``<X>ParadigmConfig.from_dict()`` — top-level paradigm
        hparam + nested sub-section dicts (agent / mcts / train / ...). The
        ``agent`` sub-dict (if any) merges ``[shape]`` base + per-paradigm
        ``[paradigm.<name>.agent]`` override.

    Raises:
        ValueError: legacy flat ``[paradigm]`` structure detected (per CC-301).
        ValueError: ``[paradigm.<name>]`` or ``[paradigm.<name>.agent]`` not a
            section (typo / wrong toml level).
    """
    pdict_root = toml_dict.get('paradigm', {})
    if not isinstance(pdict_root, dict):
        raise ValueError(
            f'cfg: [paradigm] must be a section (table of [paradigm.<name>] sub-tables), '
            f'got {type(pdict_root).__name__}'
        )

    # CC-301 hard break: detect legacy flat structure. Hybrid form: [paradigm]
    # only contains nested dicts ([paradigm.<name>]). Legacy form: [paradigm]
    # has scalar values directly (lr=1e-3 etc.). Scalar keys that ARE known
    # paradigm names indicate malformed `[paradigm.<name>] = "scalar"` and
    # are handled below as wrong-shape errors with a clearer message.
    legacy_scalar_keys = sorted(
        k for k, v in pdict_root.items() if not isinstance(v, dict) and k not in _KNOWN_PARADIGM_NAMES
    )
    if legacy_scalar_keys:
        raise ValueError(
            f'cfg: legacy flat [paradigm] structure detected (scalar keys {legacy_scalar_keys}); '
            f'use hybrid [paradigm.{paradigm_name}.X] structure instead '
            f'(per cfg-toml-restructure-paradigm-scoped CC-301)'
        )

    # CC-304: non-dispatched paradigm sections silently ignored. Extract only
    # the dispatched paradigm's section. Missing section → empty dict (paradigm
    # uses all dataclass defaults via from_dict({})).
    paradigm_section = pdict_root.get(paradigm_name, {})
    if not isinstance(paradigm_section, dict):
        raise ValueError(f'cfg: [paradigm.{paradigm_name}] must be a section, got {type(paradigm_section).__name__}')

    # Build flat dict — start from the paradigm section (top-level paradigm
    # hparam + nested sub-section dicts).
    flat: dict = dict(paradigm_section)

    # CC-305 + CC-303: [shape] is OPTIONAL top-level section providing shared
    # obs schema defaults. If present, merge into 'agent' sub-dict as base;
    # [paradigm.<name>.agent] values override [shape] per-field.
    shape = toml_dict.get('shape')
    if shape is not None:
        if not isinstance(shape, dict):
            raise ValueError(f'cfg: [shape] must be a section, got {type(shape).__name__}')
        existing_agent = flat.get('agent', {})
        if not isinstance(existing_agent, dict):
            raise ValueError(
                f'cfg: [paradigm.{paradigm_name}.agent] must be a section, got {type(existing_agent).__name__}'
            )
        # Dict merge: shape is base, agent overrides (per CC-303).
        flat['agent'] = {**shape, **existing_agent}

    return flat
