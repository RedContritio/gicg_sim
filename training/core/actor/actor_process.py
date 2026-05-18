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

    Stop signalling: either ``should_stop`` callable OR an mp.Event
    ``stop_event`` (preferred for spawned workers).
    """
    affinity = _resolve_actor_affinity(cfg)
    harden_child_env(affinity=affinity)
    if stop_event is not None:
        install_quiet_sigterm(stop_event)

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
    while not should_stop():
        spec = spec_sampler(cfg, actor_id)
        record = runner.run(spec, policy, provider)
        # Push transition list; ring/queue handles backpressure (drop on full).
        try:
            if hasattr(transition_queue, 'push'):  # SHMRing
                ok = transition_queue.push(record.transitions)
                if not ok:
                    # Ring full — yield briefly so consumer drains.
                    time.sleep(0.001)
            else:  # IPCQueue / mp.Queue
                transition_queue.put(record.transitions)
        except Exception as exc:
            # Don't bring down the actor on a transient transport hiccup.
            print(f'[actor {actor_id}] transport error: {type(exc).__name__}: {exc}')
        # Poll new weights between episodes.
        try:
            provider.update_weights()
        except Exception as exc:
            print(f'[actor {actor_id}] provider.update_weights err: {type(exc).__name__}: {exc}')


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

    def terminate(self, timeout_s: float = 10.0) -> None:
        if self._proc is None:
            return
        self.stop_event.set()
        self._proc.join(timeout=timeout_s)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)
        self._proc = None

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None
