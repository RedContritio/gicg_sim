"""tools.runs._train.dispatch — paradigm dispatch for Phase C step 6.

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Split out of :mod:`tools.runs._train.run` per the 300-
line file budget (CLAUDE.md pre-commit hook) once T-11's full paradigm
dispatch body landed alongside Phase C's lifecycle + close logic.

This module owns the cfg → paradigm → ``run_pipeline`` wiring
previously inlined into ``tools/run.py`` (deleted by L-1 per spec
§Architecture CRIT-X-1 行 28-32). It is invoked from
:func:`tools.runs._train.run._run_train_placeholder` (T-11 retains the
T-10 placeholder symbol name so Phase C tests' monkeypatches keep
working — the call site is the place tests inject failures, so the
external surface stays stable).

Spec cross-refs (``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``):

- 行 28-32 §Architecture CRIT-X-1 method A (full paradigm dispatch
           migration, no thin shim retained over the old entry)
- 行 76-96 §Per-run dir layout — prebuilt artifacts_dir is the per-run
           dir Phase A allocated under ``artifacts/<ts>_<NNN>_<label>/``
- 行 50    §Architecture step 4 — cfg_resolved.toml is the post extends
           + override snapshot Phase B wrote; reading it back here does
           NOT re-resolve extends (loader.py 行 120 pops the field
           after merging the chain)
"""

from __future__ import annotations

from tools.runs._train.setup import SetupState


def run_paradigm_train(state: SetupState) -> None:
    """Load resolved cfg, resolve paradigm, build factories, run pipeline.

    Loads cfg from ``<state.artifacts_dir>/cfg_resolved.toml`` (Phase B
    wrote this post extends + post --override, with ``meta.extends``
    already stripped by :func:`load_with_extends`'s line-120 pop, so a
    second ``load_cfg`` does **not** re-resolve extends — see spec
    §Architecture CRIT-X-1 行 28-32 method A "完整迁移").

    Resolves the paradigm class via the central registry, builds the
    paradigm-supplied opponent pool + env factory (mirroring the
    legacy ``tools/run.py`` dispatch shape), then hands everything to
    :func:`run_pipeline` with ``prebuilt_artifacts_dir=state.artifacts_dir``
    so the driver writes ckpts / metrics into the per-run dir Phase A
    already mkdir'd — does NOT re-derive a different dir from
    ``cfg.checkpoint.artifacts_root`` (which lacks the NNN segment).

    Raises whatever the underlying ``load_cfg`` / paradigm.make_* /
    ``run_pipeline`` chain raises. Phase C wraps the call in a broad
    ``except BaseException`` (spec 行 54), so any error mapping to
    ``status=failed`` happens in the caller, not here.
    """
    # Lazy import — keeps test_train_close.py (which monkeypatches the
    # _run_train_placeholder shim to a no-op or raiser) free of the
    # full training stack import cost. Real production main() reaches
    # this branch and pays the import once per process.
    from training.core.config.loader import load_cfg
    from training.core.env_factory import make_env_factory
    from training.core.pipeline import run_pipeline
    from training.paradigms import resolve as resolve_paradigm

    # cfg_resolved.toml is the immutable post-extends + post --override
    # snapshot Phase B wrote. Loading via load_cfg routes it through the
    # full validate + paradigm-dispatch pipeline (loader.py 行 269-283)
    # so any schema violation in the resolved cfg surfaces here, not in
    # the middle of a paradigm-specific factory call. ``overrides=[]``
    # because Phase A already applied them.
    cfg_resolved_path = state.artifacts_dir / 'cfg_resolved.toml'
    cfg = load_cfg(cfg_resolved_path, overrides=[])

    paradigm = resolve_paradigm(cfg.meta.paradigm)

    # obs_config_json=None — unified pipeline cfgs (DMC / PPO / CFR / BC)
    # don't carry ObsConfig; engine applies all-on shuffle defaults.
    # AZ legacy path under async_loop.py threads cfg.obs.to_engine_json()
    # explicitly; the unified registry path doesn't take that branch.
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    # Paradigm-supplied opponent pool. Built here in the main process
    # (driver doesn't know OpponentPool type). Mirrors tools/run.py 行
    # 161-171 dispatch shape: if the paradigm exposes make_opponent_pool
    # we instantiate the network once + build the pool that closes over
    # the same AgentConfig the driver will later use (the driver also
    # calls make_network internally; the second build is harmless since
    # paradigm.make_network caches via ``self._network``).
    opp_pool = None
    if hasattr(paradigm, 'make_opponent_pool'):
        network = paradigm.make_network(cfg)
        opp_pool = paradigm.make_opponent_pool(cfg, network)

    run_pipeline(
        cfg,
        paradigm,
        env_factory=env_factory,
        opp_pool=opp_pool,
        eval_server=None,  # EvalServer wiring stays out of T-11 (post-redesign backlog)
        resume_from=None,  # resume path lands in T-12 via SetupState extension
        prebuilt_artifacts_dir=state.artifacts_dir,
    )
