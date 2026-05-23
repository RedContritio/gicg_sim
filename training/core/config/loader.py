"""TOML cfg loader with extends chain + override + strict validation.

Spec: config-schema/spec.md §4 + §5 (loader sequence).
Pipeline: load_toml_with_extends → apply_overrides →
``resolve_inheritance`` → ``validate_schema`` → paradigm dispatch →
build dataclass.

Loader strictness (CS4):
- unknown top-level key → raise
- missing required → raise
- placement R1-R7 enforced post-resolve
- paradigm dispatch (FU-W1B): cfg.paradigm dict is validated against
  the paradigm-specific schema (e.g. DMCParadigmConfig.from_dict) so
  unknown paradigm-section fields fail at load time, not later when
  the adapter would surface a much later traceback.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Optional

from training.core.config.base import (
    CheckpointCfg,
    DebugCfg,
    EvalCfg,
    InferenceCfg,
    LearnerCfg,
    MetaCfg,
    PipelineCfg,
    RemoteInferenceCfg,
    RuntimeCfg,
    ScenarioCfg,
    TrainingConfig,
)
from training.core.config.inheritance import resolve_inheritance
from training.core.config.schema import check_extends_placement_sync, validate_schema


MAX_EXTENDS_DEPTH = 5


def _load_paradigm_validator(paradigm: str) -> Callable[[dict], Any]:
    """Resolve `cfg.meta.paradigm` → paradigm-specific `from_dict` validator.

    Lazy import keeps cross-paradigm transitive deps out of cfg load
    when the user is loading a single-paradigm cfg. Raises ValueError
    if the paradigm name is unknown (orthogonal to PARADIGM_VALUES enum
    check in schema.py — that check fires first if paradigm isn't in
    the closed set)."""
    if paradigm == 'dmc':
        from training.paradigms.dmc.config import DMCParadigmConfig

        return DMCParadigmConfig.from_dict
    if paradigm == 'az':
        from training.paradigms.az.config import AZParadigmConfig

        return AZParadigmConfig.from_dict
    if paradigm == 'bc':
        from training.paradigms.bc.config import BCParadigmConfig

        return BCParadigmConfig.from_dict
    if paradigm == 'ppo':
        from training.paradigms.ppo.config import PPOParadigmConfig

        return PPOParadigmConfig.from_dict
    if paradigm == 'cfr':
        from training.paradigms.cfr.config import CFRParadigmConfig

        return CFRParadigmConfig.from_dict
    raise ValueError(f'config: no paradigm validator registered for meta.paradigm={paradigm!r}')


def _read_toml(path: Path) -> dict:
    """Read TOML file (Python ≥3.11 tomllib; fall back to tomli)."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover — python <3.11 fallback
        import tomli as tomllib  # type: ignore
    with open(path, 'rb') as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge ``override`` into a copy of ``base``. Child wins on
    leaf conflict; nested dicts merge recursively."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_with_extends(path: Path, depth: int = 0) -> dict:
    """Recursively resolve ``meta.extends`` chain. Deep merge child over
    parent; placement R6 sync checked per merge step."""
    if depth > MAX_EXTENDS_DEPTH:
        raise ValueError(f'config: extends chain深度 > {MAX_EXTENDS_DEPTH} 防环 (loop suspected)')
    cfg = _read_toml(path)
    extends = cfg.get('meta', {}).get('extends')
    if not extends:
        return cfg

    # Resolve extends path relative to current cfg directory.
    extends_path = (path.parent / extends).resolve()
    if not extends_path.exists():
        raise FileNotFoundError(f'config: meta.extends={extends!r} resolved to {extends_path} but file missing')
    parent = load_with_extends(extends_path, depth + 1)

    # R6 placement sync check before merge.
    for inf_path in ('pipeline.inference', 'eval.inference'):
        parent_inf = _get_nested(parent, inf_path)
        child_inf = _get_nested(cfg, inf_path)
        if child_inf is not None:
            check_extends_placement_sync(parent_inf, child_inf, inf_path)

    merged = _deep_merge(parent, cfg)
    # Clear extends on merged result (resolved already).
    merged.get('meta', {}).pop('extends', None)
    return merged


def _get_nested(d: dict, path: str) -> Optional[Any]:
    cur: Any = d
    for seg in path.split('.'):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _apply_overrides(cfg: dict, overrides: list) -> dict:
    """Apply CLI ``--override key.path=value`` list. Values are parsed
    as int / float / bool / str via the obvious rules."""
    out = copy.deepcopy(cfg)
    for ovr in overrides:
        if '=' not in ovr:
            raise ValueError(f'override: {ovr!r} missing = (use key.path=value)')
        key, val_str = ovr.split('=', 1)
        # Parse value type
        if val_str.lower() in ('true', 'false'):
            value: Any = val_str.lower() == 'true'
        else:
            try:
                value = int(val_str)
            except ValueError:
                try:
                    value = float(val_str)
                except ValueError:
                    value = val_str
        # Set nested
        segments = key.split('.')
        cur = out
        for seg in segments[:-1]:
            if seg not in cur or not isinstance(cur[seg], dict):
                cur[seg] = {}
            cur = cur[seg]
        cur[segments[-1]] = value
    return out


def _build_inference(d: Optional[dict]) -> Optional[InferenceCfg]:
    if d is None:
        return None
    remote_d = d.get('remote')
    remote = RemoteInferenceCfg(**remote_d) if remote_d is not None else None
    return InferenceCfg(
        placement=d['placement'],
        version_tag=d.get('version_tag', 'latest'),
        device=d.get('device'),
        remote=remote,
    )


def _build_dataclass(cfg: dict, paradigm_flat: dict) -> TrainingConfig:
    """Map resolved dict → TrainingConfig nested dataclasses.

    Args:
        cfg: resolved top-level cfg dict (post extends + override + inheritance).
        paradigm_flat: paradigm-scoped flat dict produced by
            ``training.core.cfg.loader.load_paradigm_cfg`` (extracts
            ``[paradigm.<name>]`` + merges ``[shape]`` into agent sub-dict).
            See cfg-toml-restructure-paradigm-scoped N6.5 / CC-306.
    """
    meta_d = cfg['meta']
    meta = MetaCfg(
        seed=meta_d['seed'],
        paradigm=meta_d['paradigm'],
        run_label=meta_d['run_label'],
        device=meta_d.get('device', 'cpu'),
        extends=meta_d.get('extends'),
    )

    pipe_d = cfg['pipeline']
    learner_d = pipe_d.get('learner') or {}
    actor_backend = pipe_d.get('actor_backend', 'python')
    if actor_backend not in ('python', 'go'):
        raise ValueError(f'pipeline.actor_backend must be "python" or "go", got {actor_backend!r}')
    pipeline = PipelineCfg(
        mode=pipe_d.get('mode', 'serial'),
        num_actors=pipe_d.get('num_actors', 1),
        actor_backend=actor_backend,
        inference=_build_inference(pipe_d.get('inference')),
        learner=LearnerCfg(device=learner_d.get('device'), seed=learner_d.get('seed')),
        actor_seed=pipe_d.get('actor_seed'),
    )

    sc_d = cfg['scenario']
    scenario = ScenarioCfg(
        team_0=sc_d['team_0'],
        team_1=sc_d['team_1'],
        pool=sc_d.get('pool'),
        max_rounds=sc_d.get('max_rounds', 0),
        deck_padding=sc_d.get('deck_padding'),
        char_pool=sc_d.get('char_pool'),
        team_size=sc_d.get('team_size', 1),
        disjoint_teams=sc_d.get('disjoint_teams', False),
        card_pool=sc_d.get('card_pool'),
        data_dir=sc_d.get('data_dir'),
        fix_dice=sc_d.get('fix_dice'),
        obs_mask=sc_d.get('obs_mask'),
    )

    eval_cfg = None
    if 'eval' in cfg:
        eval_d = cfg['eval']
        # strict — 不容忍 [eval] 内未知字段(同 [debug]/CS4 风格)
        allowed_eval = {f.name for f in EvalCfg.__dataclass_fields__.values()}
        unknown_eval = set(eval_d.keys()) - allowed_eval
        if unknown_eval:
            raise ValueError(
                f'config: unknown field in [eval]: {sorted(unknown_eval)} (allowed: {sorted(allowed_eval)})'
            )
        eval_cfg = EvalCfg(
            n_workers=eval_d.get('n_workers', 1),
            schedule=eval_d.get('schedule', 'every_1000_steps'),
            inference=_build_inference(eval_d.get('inference')),
            scenario_seed=eval_d.get('scenario_seed'),
            worker_seed=eval_d.get('worker_seed'),
            host=eval_d.get('host', 'localhost'),
            port=eval_d.get('port', 9100),
            cpu_affinity=eval_d.get('cpu_affinity'),
        )

    ck_d = cfg.get('checkpoint', {})
    checkpoint = CheckpointCfg(
        save_every=ck_d.get('save_every', 1000),
        keep_last_n=ck_d.get('keep_last_n', 5),
        artifacts_root=ck_d.get('artifacts_root', 'artifacts'),
    )

    dbg_d = cfg.get('debug', {})
    # strict — 不容忍 [debug] 内未知字段(同其他段 CS4 风格;dev API 拼写错 fail-loud)
    allowed_dbg = {f.name for f in DebugCfg.__dataclass_fields__.values()}
    unknown = set(dbg_d.keys()) - allowed_dbg
    if unknown:
        raise ValueError(f'config: unknown field in [debug]: {sorted(unknown)} (allowed: {sorted(allowed_dbg)})')
    debug = DebugCfg(**dbg_d) if dbg_d else DebugCfg()

    rt_d = cfg.get('runtime', {})
    # strict — 同 [debug] 风格;runtime 字段拼写错 fail-loud。
    allowed_rt = {f.name for f in RuntimeCfg.__dataclass_fields__.values()}
    unknown_rt = set(rt_d.keys()) - allowed_rt
    if unknown_rt:
        raise ValueError(f'config: unknown field in [runtime]: {sorted(unknown_rt)} (allowed: {sorted(allowed_rt)})')
    runtime = RuntimeCfg(**rt_d) if rt_d else RuntimeCfg()

    return TrainingConfig(
        meta=meta,
        pipeline=pipeline,
        scenario=scenario,
        paradigm=paradigm_flat,
        eval=eval_cfg,
        checkpoint=checkpoint,
        debug=debug,
        runtime=runtime,
    )


def load_cfg(path: str | Path, overrides: Optional[list] = None) -> TrainingConfig:
    """End-to-end loader: extends → override → resolve → validate →
    paradigm dispatch → build.

    Args:
        path: cfg TOML file path.
        overrides: ['key.path=value', ...] from CLI.
    Returns:
        TrainingConfig frozen dataclass.
    Raises:
        ValueError on any schema / inheritance / placement violation,
        OR on paradigm-specific schema violation (unknown field in
        `[paradigm]` block).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'config: cfg file {p} not found')
    raw = load_with_extends(p)
    if overrides:
        raw = _apply_overrides(raw, list(overrides))
    resolved = resolve_inheritance(raw)
    validate_schema(resolved)
    # FU-W1B: dispatch `[paradigm]` section through paradigm-specific
    # validator. Catches unknown paradigm-section fields at load time
    # rather than at first adapter use (much later in the run lifecycle).
    paradigm = resolved['meta']['paradigm']
    validator = _load_paradigm_validator(paradigm)
    # cfg-toml-restructure-paradigm-scoped N6 / CC-306:
    # Extract hybrid `[paradigm.<name>]` + `[paradigm.<name>.X]` sub-sections
    # + merge top-level `[shape]` into agent sub-dict. Returns flat dict
    # equivalent to legacy `[paradigm]` shape, feedable to from_dict().
    from training.core.cfg.loader import load_paradigm_cfg

    paradigm_flat = load_paradigm_cfg(resolved, paradigm)
    validator(paradigm_flat)
    return _build_dataclass(resolved, paradigm_flat)
