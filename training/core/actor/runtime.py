"""Runtime — multi-process actor / eval / inference lifecycle manager.

Owns:

- N :class:`ActorProcess` workers
- K :class:`InferenceServer` workers (when ``placement='remote'``)
- :class:`WeightsSHM` (multi-slot weight publishing)
- Eval worker processes (TODO — wired via ``start_eval_workers``)

Driver pattern::

    rt = Runtime(cfg)
    rt.start_actors(n=4, actor_kwargs={...})
    rt.start_inference_pool(2, server_factory=...)
    # ... train loop ...
    rt.publish_weights(state_dict, version=42)
    rt.close()

P3-A skeleton "record intent only" is now gone — every ``start_*`` call
actually spawns processes.
"""

from __future__ import annotations

import signal
from typing import Any, Callable, List, Optional

from training.core.actor._mp_helpers import get_ctx
from training.core.actor.actor_process import ActorProcess
from training.core.actor.weights_shm import WeightsSHM


class Runtime:
    """Spawn-ctx process orchestrator. Constructed by the driver in
    async mode; serial mode skips it entirely (collector runs in-proc)."""

    def __init__(self, cfg: Any, weights_shm: Optional[WeightsSHM] = None) -> None:
        self.cfg = cfg
        self._owns_shm = weights_shm is None
        self.weights_shm = weights_shm if weights_shm is not None else WeightsSHM()
        self._actor_procs: List[ActorProcess] = []
        self._eval_procs: List = []
        self._inference_servers: List = []
        self._closed = False
        self._parent_handlers_installed = False

    # ---------- actor ---------- #
    def start_actors(
        self,
        n_actors: int,
        actor_kwargs_factory: Optional[Callable[[int], dict]] = None,
        actor_kwargs: Optional[dict] = None,
    ) -> List[ActorProcess]:
        """Spawn ``n_actors`` ActorProcess workers.

        Per-actor kwargs are produced either by ``actor_kwargs_factory(actor_id)``
        (preferred — lets caller derive per-actor seed / queue assignment)
        or shared via ``actor_kwargs``. At least one must be provided.
        """
        if actor_kwargs_factory is None and actor_kwargs is None:
            raise ValueError('Runtime.start_actors: pass actor_kwargs_factory or actor_kwargs')
        spawned = []
        for i in range(n_actors):
            kw = actor_kwargs_factory(i) if actor_kwargs_factory is not None else dict(actor_kwargs)
            ap = ActorProcess(actor_id=i, cfg=self.cfg, kwargs=kw)
            ap.spawn()
            self._actor_procs.append(ap)
            spawned.append(ap)
        return spawned

    def actor_procs(self) -> List[ActorProcess]:
        return list(self._actor_procs)

    # ---------- inference ---------- #
    def start_inference_pool(
        self,
        pool_size: int,
        server_factory: Callable[[int], Any],
        wait_ready_s: float = 15.0,
    ) -> List[Any]:
        """Spawn ``pool_size`` inference server processes. Caller's
        ``server_factory(idx)`` returns a fresh :class:`InferenceServer`
        (constructed but not started)."""
        servers = []
        for i in range(pool_size):
            srv = server_factory(i)
            srv.start(wait_ready_s=wait_ready_s)
            self._inference_servers.append(srv)
            servers.append(srv)
        return servers

    def inference_servers(self) -> list:
        return list(self._inference_servers)

    # ---------- eval ---------- #
    def start_eval_workers(self, n_workers: int, worker_factory: Callable[[int], Any]) -> list:
        spawned = []
        for i in range(n_workers):
            w = worker_factory(i)
            # Worker objects are expected to have a .spawn() / .start() of their own.
            if hasattr(w, 'spawn'):
                w.spawn()
            elif hasattr(w, 'start'):
                w.start()
            self._eval_procs.append(w)
            spawned.append(w)
        return spawned

    # ---------- weights ---------- #
    def publish_weights(self, state_dict: dict, version: int, tag: str = 'latest') -> None:
        self.weights_shm.write(tag, state_dict, version)

    def snapshot_for_eval(self, eval_id: str) -> int:
        return self.weights_shm.snapshot('latest', f'snapshot_{eval_id}')

    # ---------- signal handling ---------- #
    def install_signal_handlers(self) -> None:
        """Install parent-side SIGTERM/SIGINT → graceful close.
        Idempotent. Skips if called outside the main thread."""
        if self._parent_handlers_installed:
            return

        def _handler(signum, frame):  # pragma: no cover — signal path
            try:
                self.close()
            finally:
                # Re-raise default behavior so process exits.
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
            self._parent_handlers_installed = True
        except (ValueError, OSError):
            pass

    # ---------- lifecycle ---------- #
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for ap in self._actor_procs:
            try:
                ap.terminate()
            except Exception:
                pass
        self._actor_procs.clear()
        for w in self._eval_procs:
            try:
                if hasattr(w, 'terminate'):
                    w.terminate()
                elif hasattr(w, 'stop'):
                    w.stop()
            except Exception:
                pass
        self._eval_procs.clear()
        for s in self._inference_servers:
            try:
                s.stop()
            except Exception:
                pass
        self._inference_servers.clear()
        if self._owns_shm:
            try:
                self.weights_shm.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# Back-compat alias — some downstream callers may use ActorRuntime.
ActorRuntime = Runtime


# Re-export get_ctx for convenience (callers building factories often
# need the same context to create queues / events).
mp_ctx = get_ctx
