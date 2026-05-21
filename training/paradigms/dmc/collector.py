"""DMC collectors — serial + multi-process (per-class docstrings).

``_dmc_build_*`` resolve paradigm-supplied factories (picklable dotted
paths) inside spawned children; required by the legacy ``_bootstrap``
path. The current mp path wires ``training.paradigms.dmc.mp_factories``
directly (E target / P2-PoC) and bypasses these resolvers."""

from __future__ import annotations

import random
from typing import Any, Optional

from training.core.actor.ipc.ring import SHMRing
from training.core.actor.runtime import Runtime
from training.core.protocols import CollectorOutput
from training.paradigms.dmc._episode import play_one_episode
from training.paradigms.dmc._opponent import OpponentPool


def derive_seed(master_seed: int, *labels: Any) -> int:
    """Deterministic seed derivation from master + arbitrary labels."""
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        s = repr(lab).encode('utf-8')
        for b in s:
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


class DMCSerialCollector:
    """Single-process DMC collector. Lazy LocalNetworkProvider(
    DMCInferenceNet(agent.net)); the pipeline ``provider`` arg is
    ignored (DMC's 15-tensor obs_dict shape mismatch). Indirection
    unblocks GPU collector + torch.compile."""

    requires_network_in_collect = True

    def __init__(self, cfg: Any, paradigm_cfg: Any, agent: Any, opp_pool: OpponentPool, env: Any) -> None:
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.agent = agent
        self.opp_pool = opp_pool
        self.env = env
        self._episode_seq = 0
        self._master_seed = int(cfg.meta.seed)
        self._rng_side = random.Random(derive_seed(self._master_seed, 'side'))
        self._rng_action = random.Random(derive_seed(self._master_seed, 'explore-action'))
        self._dmc_provider: Optional[Any] = None

    def _ensure_dmc_provider(self) -> Any:
        # Lazy LocalNetworkProvider(DMCInferenceNet(agent.net)); same
        # nn.Module so optimizer.step() updates are visible.
        if self._dmc_provider is None:
            from training.core.actor.network_provider import LocalNetworkProvider
            from training.paradigms.dmc.inference_net import DMCInferenceNet

            infer_net = DMCInferenceNet(self.agent.net).to(self.agent.device).eval()
            self._dmc_provider = LocalNetworkProvider(
                infer_net,
                device=str(self.agent.device),
                inference_acceleration=self._read_inference_acceleration(),
            )
        return self._dmc_provider

    def _read_inference_acceleration(self) -> str:
        p = getattr(self.cfg, 'paradigm', None)
        if hasattr(p, 'inference_acceleration'):
            return getattr(p, 'inference_acceleration') or 'none'
        if isinstance(p, dict):
            return p.get('inference_acceleration', 'none') or 'none'
        return 'none'

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        del provider  # ignored — see class docstring
        dmc_provider = self._ensure_dmc_provider()
        episodes_for_buffer: list = []
        episode_stats: list = []
        n_trans_total = 0
        for _ in range(max(1, n_episodes)):
            self._episode_seq += 1
            ep_seed = derive_seed(self._master_seed, 'episode', self._episode_seq)
            self.env.reset(seed=ep_seed)
            opponent = self.opp_pool.sample()
            agent_side = self._rng_side.randint(0, 1)
            transitions, G, n_steps = play_one_episode(
                self.env,
                self.agent,
                opponent,
                agent_side=agent_side,
                max_steps=self.pcfg.max_game_steps,
                rng_action=self._rng_action,
                provider=dmc_provider,
            )
            if transitions:
                episodes_for_buffer.append((transitions, G))
                n_trans_total += len(transitions)
            episode_stats.append(
                {
                    'ep_idx': self._episode_seq,
                    'n_steps': int(n_steps),
                    'G': float(G),
                    'opp': type(opponent).__name__,
                    'side': int(agent_side),
                    'n_transitions': len(transitions),
                }
            )
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'dmc_episodes': episodes_for_buffer},
            n_units=n_trans_total,
        )

    def close(self) -> None:
        if hasattr(self.env, 'close'):
            try:
                self.env.close()
            except Exception:
                pass

    def state_dict(self) -> dict:
        return {
            'episode_seq': self._episode_seq,
            'master_seed': self._master_seed,
            'rng_side': self._rng_side.getstate(),
            'rng_action': self._rng_action.getstate(),
        }

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._master_seed = sd.get('master_seed', self._master_seed)
        if 'rng_side' in sd:
            self._rng_side.setstate(sd['rng_side'])
        if 'rng_action' in sd:
            self._rng_action.setstate(sd['rng_action'])


# ---------- DMC multi-process collector (FU-W3b-DMC) ---------- #
# Mp internals (legacy resolvers + spec_sampler + inference pool helper)
# live in _mp_internal to keep this file under 300 lines. Re-export the
# names the existing tests import via `from collector import ...`.
from training.paradigms.dmc._mp_internal import (  # noqa: E402,F401
    _DMC_ACTOR_EP_SEQ,
    _adapt_episode_record,
    _dmc_build_env_factory,
    _dmc_build_opp_registry,
    _dmc_build_policy,
    _dmc_build_provider,
    _dmc_spec_sampler,
    _resolve_paradigm_factory,
    _spawn_inference_pool,
    _terminal_z,
)


class DMCMultiProcessCollector:
    """DMC async collector — N actor procs + SHM ring + WeightsSHM.
    ``collect`` drains the ring; ``sync_weights`` re-publishes."""

    requires_network_in_collect = True

    def __init__(
        self,
        cfg,
        paradigm_cfg,
        network,
        opp_pool,
        env_factory,
        *,
        runtime: Optional[Runtime] = None,
        ring: Optional[SHMRing] = None,
    ) -> None:
        self.cfg, self.pcfg, self.network = cfg, paradigm_cfg, network
        self.opp_pool, self.env_factory = opp_pool, env_factory
        self._master_seed = int(cfg.meta.seed)
        self._episode_seq = 0
        self._weights_version = 0
        self.runtime = runtime if runtime is not None else Runtime(cfg)
        # SHMRing sizing: each DMC EpisodeRecord pickles to ~270 KB per
        # transition (hook_ir + action_refs + action_payments dominate);
        # episode length scales with card-pool size. Measured payloads:
        # 4-5 MB for the 6-card smoke pool, 10-13 MB for v_legacy
        # 26-card pool. We ship 32 MB × 64 slots = 2 GB SHM to keep
        # headroom for outlier episodes (100+ transitions on richer
        # pools). Capacity 64 caps queued backlog — actors backpressure
        # via push==False yield rather than memory pressure.
        self.ring = ring if ring is not None else SHMRing(capacity=64, slot_payload_max=32 * 1024 * 1024)
        self._spawned = False
        self._inference_server: Optional[Any] = None
        self._inference_clients: list = []
        # InfServer stats hook — set via attach_metrics_logger(); _bootstrap
        # wires a mp.Queue between InfServer 子进程 + master logger drainer。
        self._metrics_logger: Optional[Any] = None

    def attach_metrics_logger(self, logger: Any) -> None:
        """Wire master MetricsLogger to drain InfServer stats — kind="inf_server"
        rows入 metrics.jsonl(queue_depth / batch_size / process_ms / batches_per_sec
        etc.,每 5s aggregate)。 Idempotent before _bootstrap;after spawn
        无效(InfServer 已起,stats_q 已固定)。"""
        if self._spawned:
            return
        self._metrics_logger = logger

    def _bootstrap(self) -> None:
        """Publish initial weights, stand up shared InferenceServer + N
        InferenceClients, then spawn actors. Idempotent. Mp factories
        in :mod:`training.paradigms.dmc.mp_factories`."""
        if self._spawned:
            return
        sd_cpu = {k: v.detach().cpu() for k, v in self.network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        n_actors = int(getattr(self.cfg.pipeline, 'num_actors', 1))
        self._inference_server, self._inference_clients = _spawn_inference_pool(
            self.cfg, self.network, n_actors, metrics_logger=self._metrics_logger
        )
        mp = 'training.paradigms.dmc.mp_factories'
        coll = 'training.paradigms.dmc.collector'
        base = {
            'build_env_factory_path': f'{mp}.build_dmc_env_factory',
            'build_opp_registry_path': f'{mp}.build_dmc_opp_registry',
            'build_policy_path': f'{coll}._dmc_build_policy',
            'build_provider_path': f'{mp}.build_dmc_provider',
            'spec_sampler_path': f'{coll}._dmc_spec_sampler',
            'transition_queue': self.ring,
            # DMC mp consumes record.winner (for MC return G) +
            # per-transition payload['dmc_obs_dict'] (rebuilt by the
            # remote provider). Force EpisodeRecord push (vs the default
            # bare transitions list other paradigms use).
            'push_episode_record': True,
        }
        clients = self._inference_clients
        self.runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda i: dict(base, inference_client=clients[i]),
        )
        self._spawned = True

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Drain SHM ring → CollectorOutput. Ring item is an EpisodeRecord
        (needs winner + payload['dmc_obs_dict']); n_dropped surfaces
        wiring bugs (should always be 0 — observe_env precedes act)."""
        del provider  # mp mode: actors own their own providers
        self._bootstrap()
        episodes_for_buffer: list = []
        episode_stats: list = []
        n_trans_total = 0
        n_dropped_total = 0
        n_pulled = 0
        for _ in range(max(1, int(n_episodes))):
            item = self.ring.try_pop()
            if item is None:
                break
            self._episode_seq += 1
            dmc_trans, n_dropped = _adapt_episode_record(item)
            winner = int(getattr(item, 'winner', -1))
            G = _terminal_z(winner, our_player=0)
            n_trans = len(dmc_trans)
            if dmc_trans:
                episodes_for_buffer.append((dmc_trans, G))
            n_trans_total += n_trans
            n_dropped_total += n_dropped
            episode_stats.append(
                {
                    'ep_idx': self._episode_seq,
                    'n_transitions': n_trans,
                    'n_dropped': n_dropped,
                    'winner': winner,
                    'G': float(G),
                    'source': 'mp_actor',
                }
            )
            n_pulled += 1
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'dmc_episodes': episodes_for_buffer, 'n_pulled': n_pulled, 'n_dropped': n_dropped_total},
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Publish learner weights to WeightsSHM (actors poll between episodes)."""
        self._weights_version += 1
        sd_cpu = {k: v.detach().cpu() for k, v in network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        return self._weights_version

    def close(self) -> None:
        # Order: clients → server.stop → runtime.close → ring.close.
        def _safely(fn):
            try:
                fn()
            except Exception:
                pass

        for c in self._inference_clients:
            _safely(c.close)
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


DMCAsyncCollector = DMCMultiProcessCollector  # public alias (FU-W3b-DMC)
