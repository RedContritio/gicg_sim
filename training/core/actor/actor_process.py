"""ActorProcess — real mp.Process actor worker.

``actor_main`` is the spawn target. It must stay top-level (picklable);
all paradigm-specific builders are passed by *qualified dotted name*
(``module.attr``) rather than callable refs so the spawn target picks
them up from the child's import. This keeps the API paradigm-agnostic
while staying spawn-safe.

The caller pre-validates builder paths before spawning by calling
:func:`resolve_builder` once in the parent — failures surface in the
parent, not the child.
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable, Optional

from training.core.actor._mp_helpers import (
    get_ctx,
    harden_child_env,
    install_quiet_sigterm,
)
from training.core.actor.episode_runner import EpisodeRunner
from training.core.config.inheritance import derive_seed
from training.core.perf import trace as _perf_trace
from training.core.protocols import EpisodeSpec


def _resolve_actor_affinity(cfg: Any) -> Optional[list[int]]:
    """Read ``cfg.paradigm.cpu_affinity_actors`` if present (paradigm-aware).

    Returns ``None`` for paradigms that don't define this field — affinity
    is a per-paradigm opt-in. Robust to both shapes of ``cfg.paradigm``
    we observed in the loader (see
    ``training/core/config/loader.py:_build_dataclass``): runtime cfgs
    carry a flat dict (paradigm_flat) while in-process construction in
    tests may set a typed ``DMCParadigmConfig`` instance.
    """
    paradigm = getattr(cfg, 'paradigm', None)
    if paradigm is None:
        return None
    if hasattr(paradigm, 'cpu_affinity_actors'):
        return paradigm.cpu_affinity_actors
    if isinstance(paradigm, dict):
        return paradigm.get('cpu_affinity_actors')
    return None


def resolve_builder(path: str) -> Callable:
    """Import ``module.attr`` → return the attr. Raise ImportError /
    AttributeError up to the caller for early validation."""
    mod_name, _, attr = path.rpartition('.')
    if not mod_name:
        raise ValueError(f'resolve_builder: {path!r} must be dotted (module.attr)')
    mod = importlib.import_module(mod_name)
    if not hasattr(mod, attr):
        raise AttributeError(f'resolve_builder: {mod_name} has no attribute {attr!r}')
    return getattr(mod, attr)


def actor_main(
    actor_id: int,
    cfg: Any,
    *,
    build_env_factory: Callable[[Any, int], Any] = None,
    build_opp_registry: Callable[[Any], Any] = None,
    build_policy: Callable[[Any, int], Any] = None,
    build_provider: Callable[[Any, int], Any] = None,
    spec_sampler: Callable[[Any, int], EpisodeSpec] = None,
    transition_queue: Any = None,
    should_stop: Optional[Callable[[], bool]] = None,
    # Dotted-path versions (preferred for cross-process spawn) ───────
    build_env_factory_path: Optional[str] = None,
    build_opp_registry_path: Optional[str] = None,
    build_policy_path: Optional[str] = None,
    build_provider_path: Optional[str] = None,
    spec_sampler_path: Optional[str] = None,
    inference_client: Any = None,
    stop_event: Any = None,
    push_episode_record: bool = False,
) -> None:
    """Actor loop — runs episodes until stop is requested.

    Two calling conventions:

    - In-proc: pass callable ``build_*`` + ``spec_sampler`` directly.
    - Cross-process spawn: pass ``*_path`` dotted strings; this
      function resolves them inside the child after env hardening.

    ``inference_client`` (optional): parent-constructed InferenceClient
    handed in via per-actor kwargs. When provided, ``build_provider`` is
    called with ``inference_client=`` kwarg so paradigm factories can
    construct a :class:`RemoteNetworkProvider` routed to a shared
    :class:`InferenceServer`. Backward compatible: old factories with
    signature ``(cfg, actor_id)`` are still called without the kwarg.

    ``push_episode_record`` (default False): when False, pushes
    ``record.transitions`` (list[Transition]) onto the queue — the
    historical contract AZ + others rely on. When True, pushes the full
    :class:`EpisodeRecord` so the collector can read ``record.winner``
    + per-transition payload (DMC needs both to reconstruct
    ``DmcTransition`` + backfill MC return G). Opt-in to avoid
    perturbing existing paradigm collectors.

    Stop signalling: either ``should_stop`` callable OR an mp.Event
    ``stop_event`` (preferred for spawned workers).
    """
    affinity = _resolve_actor_affinity(cfg)
    harden_child_env(affinity=affinity)
    if stop_event is not None:
        install_quiet_sigterm(stop_event)
    # cfg-driven enable (post 2026-05-23 env var 砍后必需) — actor spawn target
    # 拿到完整 TrainingConfig,读 cfg.debug.perf_trace + 配套字段 set 模块 state
    # 后 configure 才真打开 handle。 cfg.debug.perf_trace=False (default) 时
    # enable_from_cfg + configure 均 no-op,hot path span() 走 _NOOP 单例。
    _perf_trace.enable_from_cfg(cfg)
    _perf_trace.configure(role='actor', id=actor_id)

    # Per-actor file logging: mp child stdout/stderr is unreliable —
    # pytest captures it, ssh strips it, sandboxes suppress it. Tee
    # everything to artifacts/_actor_logs/actor_<id>.log so debugging
    # mp crashes / silent hangs / "0 transitions" wedges is possible
    # by reading the file after the fact. Gated on env var so unit
    # tests that already capture stdout via assertions don't trip.
    import os as _os
    import sys as _sys
    from pathlib import Path as _Path

    log_dir_env = _os.getenv('ACTOR_LOG_DIR', 'artifacts/_actor_logs')
    log_dir = _Path(log_dir_env)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'actor_{actor_id}.log'
        # line-buffered so each print() is visible immediately even on crash
        _log_f = open(log_path, 'w', buffering=1, encoding='utf-8')
        _sys.stdout = _log_f
        _sys.stderr = _log_f
        print(
            f'[actor {actor_id}] log start pid={_os.getpid()} cfg.paradigm={getattr(cfg.meta, "paradigm", "?")}',
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        # If logging setup fails, fall back to original stdout — at least
        # the actor still runs. The setup-time exception goes to the
        # original stderr so the parent process can see SOMETHING.
        print(f'[actor {actor_id}] log setup failed: {type(exc).__name__}: {exc}', file=_sys.__stderr__)

    if build_env_factory is None and build_env_factory_path is not None:
        build_env_factory = resolve_builder(build_env_factory_path)
    if build_opp_registry is None and build_opp_registry_path is not None:
        build_opp_registry = resolve_builder(build_opp_registry_path)
    if build_policy is None and build_policy_path is not None:
        build_policy = resolve_builder(build_policy_path)
    if build_provider is None and build_provider_path is not None:
        build_provider = resolve_builder(build_provider_path)
    if spec_sampler is None and spec_sampler_path is not None:
        spec_sampler = resolve_builder(spec_sampler_path)

    for name, fn in [
        ('build_env_factory', build_env_factory),
        ('build_opp_registry', build_opp_registry),
        ('build_policy', build_policy),
        ('build_provider', build_provider),
        ('spec_sampler', spec_sampler),
    ]:
        if fn is None:
            raise ValueError(f'actor_main[actor_id={actor_id}]: missing {name}')
    if transition_queue is None:
        raise ValueError(f'actor_main[actor_id={actor_id}]: missing transition_queue')

    seed = derive_seed(cfg.meta.seed, 'actor', actor_id)
    env_factory = build_env_factory(cfg, seed)
    opp_registry = build_opp_registry(cfg)
    runner = EpisodeRunner(env_factory, opp_registry)
    policy = build_policy(cfg, actor_id)
    if inference_client is not None:
        provider = build_provider(cfg, actor_id, inference_client=inference_client)
    else:
        provider = build_provider(cfg, actor_id)

    if should_stop is None:
        should_stop = (lambda: stop_event.is_set()) if stop_event is not None else (lambda: False)
    try:
        while not should_stop():
            spec = spec_sampler(cfg, actor_id)
            record = runner.run(spec, policy, provider)
            # Push transition list (default) or full EpisodeRecord
            # (DMC mp path needs record.winner + per-transition payload).
            item = record if push_episode_record else record.transitions
            try:
                if hasattr(transition_queue, 'push'):  # SHMRing
                    ok = transition_queue.push(item)
                    if not ok:
                        # Ring full — yield briefly so consumer drains.
                        time.sleep(0.001)
                else:  # IPCQueue / mp.Queue
                    transition_queue.put(item)
            except Exception as exc:
                # Don't bring down the actor on a transient transport hiccup.
                print(f'[actor {actor_id}] transport error: {type(exc).__name__}: {exc}')
            # Poll new weights between episodes.
            try:
                provider.update_weights()
            except Exception as exc:
                print(f'[actor {actor_id}] provider.update_weights err: {type(exc).__name__}: {exc}')
    finally:
        _perf_trace.close()
        # Cancel mp.Queue feeder-join atexit deadlock: any cross-process
        # queue handle the actor inherited (transition_queue,
        # inference_client.{request,response}_queue) may have a
        # QueueFeederThread blocked on a pipe send whose peer has died.
        # Python's atexit Queue finalizer would then block forever on
        # thread.join. cancel_join_thread tells it to drop in-flight
        # data on close; we don't care about pending data at shutdown.
        if hasattr(provider, 'close'):
            try:
                provider.close()
            except Exception:
                pass
        for q in (transition_queue,):
            if q is None:
                continue
            for attr in ('cancel_join_thread', 'close'):
                fn = getattr(q, attr, None)
                if fn is None:
                    continue
                try:
                    fn()
                except Exception:
                    pass


class ActorProcess:
    """Wrapper that owns a single mp.Process actor.

    Usage::

        ap = ActorProcess(actor_id=0, cfg=cfg, kwargs={...})
        ap.spawn()
        # ... train ...
        ap.terminate()
    """

    def __init__(self, actor_id: int, cfg: Any, kwargs: Optional[dict] = None) -> None:
        self.actor_id = actor_id
        self.cfg = cfg
        self.kwargs = kwargs or {}
        ctx = get_ctx()
        self.stop_event = ctx.Event()
        self._proc = None

    def spawn(self) -> None:
        if self._proc is not None:
            raise RuntimeError(f'ActorProcess[{self.actor_id}].spawn: already spawned')
        ctx = get_ctx()
        kwargs = dict(self.kwargs)
        kwargs.setdefault('stop_event', self.stop_event)
        self._proc = ctx.Process(
            target=actor_main,
            args=(self.actor_id, self.cfg),
            kwargs=kwargs,
            daemon=False,
            name=f'Actor[{self.actor_id}]',
        )
        self._proc.start()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def terminate(self, timeout_s: float = 2.0) -> None:
        """Cooperative stop → SIGTERM → SIGKILL escalation.

        Actor may be blocked inside a cgo call (Go runtime owns the
        OS thread + intercepts SIGTERM). SIGKILL cannot be caught so
        it's the only guaranteed shutdown path. Grace timeouts are short
        because actors that don't respond within 2s of stop_event are
        almost certainly stuck (one DMC episode is ~100ms-1s).
        """
        if self._proc is None:
            return
        self.stop_event.set()
        self._proc.join(timeout=timeout_s)
        if self._proc.is_alive():
            self._proc.terminate()  # SIGTERM — Go may swallow
            self._proc.join(timeout=1.0)
        if self._proc.is_alive():
            self._proc.kill()  # SIGKILL — uncatchable
            self._proc.join(timeout=1.0)
        self._proc = None

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None
