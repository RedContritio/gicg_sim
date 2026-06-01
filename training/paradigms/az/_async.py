"""AZAsyncCollector — parent side of the I31 #88 AZ mp-pool unification.

Split out of ``collector.py`` to stay under the 300-line cap (mirrors
``training.paradigms.cfr._async``). N actors run selfplay games via the shared
``core/actor`` runtime (``Runtime`` + ``actor_main`` + ``SHMRing``): each spawned
``actor_main`` resolves the AZ ``mp_factories`` builders by dotted path and drives
an ``AZSelfPlayRunner`` (AB14 ``episode_runner_factory``) wrapping the EXISTING
``play_self_game`` — selfplay correctness unchanged, only the mp orchestration
differs.

**Weights live server-side** (D3=C): network evaluation is centralized in one
:class:`~training.core.inference.server.InferenceServer` (replaces the legacy
``ParallelInferencePool``). Actors route every MCTS eval through a per-actor
:class:`~training.core.inference.client.InferenceClient` over the server's
``mp.Pipe``; ``sync_weights`` pushes new learner weights to the server
(``agent.net.load_state_dict`` server-side), so — unlike DMC/PPO — AZ does NOT
publish to ``WeightsSHM`` (the per-actor ``_AZRemoteProvider.update_weights`` is
a no-op version read).
"""

from __future__ import annotations

from typing import Any, Optional

from training.core.actor.ipc.ring import SHMRing
from training.core.actor.runtime import Runtime
from training.core.protocols import CollectorOutput


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
    ) -> None:
        del env_factory  # actors rebuild env from cfg (closures unpicklable for spawn)
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
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
        """One-shot stand-up (idempotent): start the shared InferenceServer,
        push initial weights, attach N clients, then spawn actors.

        Ordering matters — the server rebuilds a RANDOM net via
        ``network_factory`` in its own process, so the live training weights
        MUST be pushed (``push_weights`` requires ``start()``) before any actor
        starts evaluating, or actors would search against random priors."""
        if self._spawned:
            return
        from training.core.inference.client import InferenceClient
        from training.core.inference.server import InferenceServer

        n_actors = int(getattr(self.cfg.pipeline, 'num_actors', None) or 1)
        server = InferenceServer(
            agent_config=self._agent_config(),
            n_workers=n_actors,
            server_cfg=getattr(self.cfg, 'inference', None),
            network_factory_path='training.paradigms.az.network.Agent',
            inference_handlers_module_path='training.paradigms.az._inference_handlers',
        )
        server.start()
        server.push_weights(_cpu_net_state_dict(self.network))
        self._inference_server = server
        self._inference_clients = [
            InferenceClient(worker_id=i, pipe=server.get_worker_pipe(i)) for i in range(n_actors)
        ]

        mp_pkg = 'training.paradigms.az.mp_factories'
        base = {
            'build_env_factory_path': f'{mp_pkg}.build_az_env_factory',
            'build_opp_registry_path': f'{mp_pkg}.build_az_opp_registry',
            'build_policy_path': f'{mp_pkg}.build_az_policy',
            'build_provider_path': f'{mp_pkg}.build_az_provider',
            'spec_sampler_path': f'{mp_pkg}.az_spec_sampler',
            # AB14: selfplay lifecycle ≠ single-sided episode — wrap play_self_game.
            'episode_runner_factory_path': f'{mp_pkg}.build_az_selfplay_runner',
            'transition_queue': self.ring,
            # Push the full _AZRunnerOutput (carries the SelfPlayResult); the
            # default bare-transitions push would drop game_static + winner.
            'push_episode_record': True,
        }
        clients = self._inference_clients
        self.runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda i: dict(base, inference_client=clients[i]),
        )
        self._spawned = True

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
                break
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
                    'discovery_count': int(sp.discovery_count),
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
        """Push learner weights to the InferenceServer (server owns the weights;
        actors route eval through it, so no WeightsSHM publish). No-op before
        ``_bootstrap`` — the server isn't up yet."""
        self._weights_version += 1
        if self._inference_server is not None:
            self._inference_server.push_weights(_cpu_net_state_dict(network))
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
