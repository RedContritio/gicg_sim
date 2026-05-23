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

from typing import Any

from tools.runs._train.setup import SetupState


def _apply_learner_affinity(cfg: Any) -> None:
    """Apply ``cfg.paradigm.cpu_affinity_learner`` to the main training process.

    Paradigm-aware via ``getattr`` (only DMC defines this field today;
    other paradigms have no such key in their ``DMCParadigmConfig``-shaped
    schema, so the function silently returns). Same dict-or-typed shape
    handling as ``training.core.actor.actor_process._resolve_actor_affinity``
    — runtime cfgs carry a flat ``paradigm_flat`` dict per
    ``training/core/config/loader.py:_build_dataclass``.

    Silently skipped on platforms without ``cpu_affinity`` (Mac):
    affinity is an optimization hint, not a correctness requirement.
    """
    paradigm = getattr(cfg, 'paradigm', None)
    if paradigm is None:
        return
    if hasattr(paradigm, 'cpu_affinity_learner'):
        affinity = paradigm.cpu_affinity_learner
    elif isinstance(paradigm, dict):
        affinity = paradigm.get('cpu_affinity_learner')
    else:
        return
    if affinity is None:
        return
    try:
        import psutil

        psutil.Process().cpu_affinity(affinity)
    except (ImportError, AttributeError, OSError):
        pass


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
    from tools._dev.mem_probe import maybe_enable_from_env as _maybe_enable_mem_probe
    from training.core.config.loader import load_cfg
    from training.core.env_factory import make_env_factory
    from training.core.perf import trace as _perf_trace
    from training.core.pipeline import run_pipeline
    from training.paradigms import resolve as resolve_paradigm

    # GICG_MEM_PROBE=1 → master-process tracemalloc + periodic RSS/top-N
    # report to stderr。 no-op when env var unset。 dispatch 入口 hook 是
    # 最早能 attach tracemalloc 且仍能看到 paradigm setup/buffer/network
    # alloc 的位置(`run_paradigm_train` 内 load_cfg/build network/spawn
    # actor 都在此后发生)。
    _maybe_enable_mem_probe()

    # Configure perf tracing for the pipeline (learner) process. Actors
    # + inference server each call configure() in their own spawn target.
    # No-op when PERF_TRACE env var is unset.
    _perf_trace.configure(role='pipeline', id=0)

    # cfg_resolved.toml is the immutable post-extends + post --override
    # snapshot Phase B wrote. Loading via load_cfg routes it through the
    # full validate + paradigm-dispatch pipeline (loader.py 行 269-283)
    # so any schema violation in the resolved cfg surfaces here, not in
    # the middle of a paradigm-specific factory call. ``overrides=[]``
    # because Phase A already applied them.
    #
    # Resume path (T-12): the current truth is the highest-version
    # ``cfg_resolved_v<N>.toml`` (spec 行 157 CRIT-6-A) — Phase B
    # writes it under the suffixed name when ``cfg_resolved_version > 1``.
    # Fresh path uses the unsuffixed ``cfg_resolved.toml``.
    cfg_resolved_path = state.artifacts_dir / _current_cfg_resolved_filename(state)
    cfg = load_cfg(cfg_resolved_path, overrides=[])

    # Pin learner-process CPU affinity *before* any heavy paradigm setup
    # so child threads spawned by torch/buffer allocators inherit the
    # cpuset. No-op on Mac and on cfgs that don't set the field.
    _apply_learner_affinity(cfg)

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

    # T-12: ``state.resume_ckpt_path`` is None on fresh path, the ckpt
    # ``Path`` on resume path. ``CheckpointManager.init_artifacts_dir``
    # treats ``resume_from`` and ``prebuilt`` as mutually exclusive (one
    # derives artifacts_dir from ``ckpt.parent.parent``, the other adopts
    # caller's dir verbatim); on resume the two yield the same dir by
    # construction (Phase A resume sets ``state.artifacts_dir =
    # ckpt.parent.parent``), so we must pass only one. Convention: pass
    # ``resume_from`` on the resume branch so ``ckpt_mgr.try_resume``
    # actually loads weights, and pass ``prebuilt`` on the fresh branch
    # so Phase A's allocated dir name (with NNN) is honored verbatim.
    if state.resume_ckpt_path is not None:
        run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            opp_pool=opp_pool,
            eval_server=None,
            resume_from=state.resume_ckpt_path,
        )
    else:
        run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            opp_pool=opp_pool,
            eval_server=None,
            prebuilt_artifacts_dir=state.artifacts_dir,
        )


def _current_cfg_resolved_filename(state: SetupState) -> str:
    """Return the cfg_resolved filename for the run's current version.

    v1 → ``cfg_resolved.toml`` (unsuffixed); vN >= 2 →
    ``cfg_resolved_v<N>.toml``. Mirrors
    :func:`tools.runs._train.snapshot._versioned_filenames` resolved
    half; kept here as a one-liner so dispatch doesn't import private
    snapshot helpers.
    """
    if state.cfg_resolved_version == 1:
        return 'cfg_resolved.toml'
    return f'cfg_resolved_v{state.cfg_resolved_version}.toml'
