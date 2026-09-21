"""AZAsyncCollector — parent side of the I31 #88 AZ mp-pool unification.

Split out of ``collector.py`` to stay under the 300-line cap (mirrors
``training.paradigms.cfr._async``). N actors run selfplay games via the shared
``core/actor`` runtime (``Runtime`` + ``actor_main`` + ``SHMRing``): each spawned
``actor_main`` resolves the AZ ``mp_factories`` builders by dotted path and drives
an ``AZSelfPlayRunner`` (AB14 ``episode_runner_factory``) wrapping the EXISTING
``play_self_game`` — selfplay correctness unchanged, only the mp orchestration
differs.

**Weights broadcast** (D3=C, two modes via ``paradigm.local_inference``):
- LOCAL (default): no server. Each actor owns a CPU Agent copy; the parent
  writes the learner's inner-net state_dict to a WeightsSHM ``latest`` slot
  (``sync_weights`` + one initial write before spawn); actors load it
  between episodes in ``provider.update_weights()``. Only the master
  process touches CUDA — no per-eval pipe round-trip, no extra CUDA
  contexts (production wedge + CUBLAS crash forensics, 2026-09-19).
- SERVER (``local_inference=False``, legacy): weights live server-side in
  one shared InferenceServer; actors route every eval through a per-actor
  InferenceClient over the server's mp.Pipe. Retained for explicit
  cross-actor batching experiments.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from training.core.actor.ipc.ring import SHMRing
from training.core.actor.runtime import Runtime
from training.core.actor.weights_shm import WeightsSHM
from training.core.protocols import CollectorOutput

# Weight-broadcast slots (ExIt async local inference):
# - WEIGHTS_TAG: the learner's inner-net state_dict; slot version is the
#   weight version actors load against.
# - RING_TAG: fixed_opponent historical-ring snapshots.
# Both ride WeightsSHM slots written by the parent's sync_weights (same
# cadence as the legacy InferenceServer weight pushes).
WEIGHTS_TAG = 'latest'
RING_TAG = 'az_hist_ring'


def _cpu_net_state_dict(network: Any) -> dict:
    """CPU detach of the eval network's parameters for transport to the
    InferenceServer. The server applies updates via ``agent.net.load_state_dict``
    (see ``core/inference/server_loop/drain.py``), so push the ``.net`` params."""
    net = network.net if hasattr(network, 'net') else network
    return {k: v.detach().cpu() for k, v in net.state_dict().items()}


class AZAsyncCollector:
    """AZ async collector — N actor processes + shared InferenceServer + SHMRing.

    Owns a :class:`Runtime` (ActorProcess pool) + one
    :class:`~training.core.inference.server.InferenceServer` (centralized eval,
    holds the weights) + N :class:`~training.core.inference.client.InferenceClient`
    threaded one-per-actor. Mirrors :class:`DMCMultiProcessCollector`'s
    server-handoff pattern; AZ-specific in that weights live server-side (no
    WeightsSHM publish — see module docstring) and actors run a selfplay
    lifecycle via the AB14 ``AZSelfPlayRunner`` rather than the default
    ``EpisodeRunner``.

    ``env_factory`` arg ignored — actors rebuild env from cfg
    (``mp_factories.build_az_env_factory``); closures are unpicklable for spawn.
    """

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        env_factory: Any = None,
        *,
        runtime: Optional[Runtime] = None,
        ring: Optional[SHMRing] = None,
        opponent_pool: Optional[Any] = None,
    ) -> None:
        del env_factory  # actors rebuild env from cfg (closures unpicklable for spawn)
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self._opponent_pool = opponent_pool  # ExIt fixed_opponent: parent-side ring source
        self._opp_ring_shm: Optional[WeightsSHM] = None
        self._weights_shm: Optional[WeightsSHM] = None  # local_inference broadcast
        self._master_seed = int(cfg.meta.seed)
        self._episode_seq = 0
        self._weights_version = 0
        self.runtime = runtime if runtime is not None else Runtime(cfg)
        # SHMRing sizing mirrors DMC: a selfplay payload (_AZRunnerOutput with a
        # SelfPlayResult — game_static hook_ir + per-step obs arrays) can run
        # 10+ MB on richer pools. 32 MB × 64 slots keeps headroom; capacity 64
        # caps queued backlog (actors backpressure via push==False yield).
        self.ring = ring if ring is not None else SHMRing(capacity=64, slot_payload_max=32 * 1024 * 1024)
        self._spawned = False
        self._inference_server: Optional[Any] = None
        self._inference_clients: list = []

    def _agent_config(self) -> Any:
        """``AgentConfig`` for the InferenceServer — the server process rebuilds
        an AZ ``Agent`` from it via ``network_factory_path`` and then receives the
        live weights through ``push_weights``. Built from ``paradigm_cfg.agent``
        (an ``ObsShape``); falls back to reconstructing the paradigm cfg from the
        ``cfg.paradigm`` dict when no typed ``paradigm_cfg`` was passed."""
        from training.core.network import AgentConfig
        from training.paradigms.az.config import AZParadigmConfig

        pcfg = self.pcfg
        if pcfg is None or not hasattr(pcfg, 'agent'):
            pcfg = AZParadigmConfig.from_dict(self.cfg.paradigm if isinstance(self.cfg.paradigm, dict) else {})
        return AgentConfig.from_obs_shape(pcfg.agent)

    def _bootstrap(self) -> None:
        from training.paradigms.az._async_bootstrap import bootstrap

        bootstrap(self)

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Drain the SHM ring → CollectorOutput. Each ring item is an
        ``_AZRunnerOutput`` carrying a ``SelfPlayResult``; the output shape
        (``az_trajectories`` = ``(game_static, steps)`` tuples) matches the
        serial :class:`AZSelfPlayCollector` so buffer ingestion is identical.
        ``n_episodes`` caps pulls per iteration."""
        del provider  # mp mode: actors own their own providers
        self._bootstrap()
        trajectories: list = []
        episode_stats: list = []
        n_trans_total = 0
        n_pulled = 0
        max_pull = max(1, int(n_episodes))
        while n_pulled < max_pull:
            item = self.ring.try_pop()
            if item is None:
                if n_pulled:
                    break
                if self.actors_alive_count() == 0:
                    raise RuntimeError('AZAsyncCollector: all actors exited before producing an episode')
                time.sleep(0.01)
                continue
            self._episode_seq += 1
            sp = item.selfplay_result
            if sp.steps:
                trajectories.append((sp.game_static, sp.steps))
                n_trans_total += int(sp.n_steps)
            episode_stats.append(
                {
                    'ep_idx': self._episode_seq,
                    'n_steps': int(sp.n_steps),
                    'winner': int(sp.winner),
                    'agent_player': sp.agent_player,
                    'discovery_count': int(sp.discovery_count),
                    # opponent_kind lives on the _AZRunnerOutput envelope
                    # (the SelfPlayResult payload is opponent-agnostic).
                    'opponent_kind': getattr(item, 'opponent_kind', None),
                    'source': 'mp_actor',
                }
            )
            n_pulled += 1
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'az_trajectories': trajectories, 'n_pulled': n_pulled},
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Republish learner weights + the fixed-opponent historical ring.

        Local mode: write the WeightsSHM ``latest`` slot (actors load it
        between episodes into their local CPU Agent). Server mode: push to
        the InferenceServer (server owns the weights; actors route eval
        through it, so no WeightsSHM weight slot). Ring slot is written on
        either mode when a fixed_opponent pool is attached. No-op before
        ``_bootstrap`` — the channels aren't up yet."""
        self._weights_version += 1
        if self._weights_shm is not None:
            self._weights_shm.write(
                WEIGHTS_TAG,
                _cpu_net_state_dict(network),
                version=self._weights_version,
            )
        if self._inference_server is not None:
            # Loud failure beats a silent wedge: if the server process died
            # (e.g. GPU context fault), weight_queue.put would block forever
            # once OS buffers fill.
            self._inference_server.check_alive()
            self._inference_server.push_weights(_cpu_net_state_dict(network))
        if self._opp_ring_shm is not None and self._opponent_pool is not None:
            self._opp_ring_shm.write(
                RING_TAG,
                {'snapshots': self._opponent_pool.snapshots()},
                version=self._weights_version,
            )
        return self._weights_version

    def actors_alive_count(self) -> int:
        """Live actor count via ``Runtime.actor_procs()`` — the async ingest
        loop uses this to detect a dead actor pool (the ring would otherwise
        stay empty forever with no error surfaced)."""
        procs = self.runtime.actor_procs() if hasattr(self.runtime, 'actor_procs') else []
        return sum(1 for ap in procs if ap.is_alive())

    @property
    def stats_queue(self) -> Any:
        """The InferenceServer's stats queue (the pipeline stats ingest drains
        it for ``kind="inf_server"`` rows). None before ``_bootstrap``."""
        return self._inference_server.stats_queue if self._inference_server is not None else None

    def close(self) -> None:
        # Order: server.stop (closes the worker pipes the parent clients share)
        # → runtime.close (terminates actors) → ring.close. The core.inference
        # InferenceClient holds no resources beyond its pipe (no .close()), so
        # dropping the refs + stopping the server is the full teardown.
        def _safely(fn):
            try:
                fn()
            except Exception:
                pass

        self._inference_clients = []
        if self._inference_server is not None:
            _safely(self._inference_server.stop)
            self._inference_server = None
        if self._opp_ring_shm is not None:
            _safely(self._opp_ring_shm.close)
            self._opp_ring_shm = None
        if self._weights_shm is not None:
            _safely(self._weights_shm.close)
            self._weights_shm = None
        _safely(self.runtime.close)
        _safely(self.ring.close)
        self._spawned = False

    def state_dict(self) -> dict:
        return {
            'episode_seq': self._episode_seq,
            'master_seed': self._master_seed,
            'weights_version': self._weights_version,
        }

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._master_seed = sd.get('master_seed', self._master_seed)
        self._weights_version = sd.get('weights_version', 0)
