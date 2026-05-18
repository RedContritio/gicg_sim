"""DMC collectors — serial + multi-process (see per-class docstrings).

Module-level builder dispatchers (``_dmc_build_*``) resolve paradigm-
supplied factories (picklable dotted paths) inside spawned children;
required by ``DMCMultiProcessCollector``'s actor bootstrap.
"""

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
    """Single-process DMC episode collector.

    Inference routes through a lazily-built
    LocalNetworkProvider(DMCInferenceNet(agent.net)). The pipeline-
    supplied ``provider`` arg to ``collect`` is ignored — the driver's
    generic provider does not match DMC's 15-tensor obs_dict contract.
    Equivalent in-proc forward to the prior in-agent path; indirection
    unblocks GPU collector inference + torch.compile.
    """

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
        # Lazy-build LocalNetworkProvider(DMCInferenceNet(agent.net));
        # same nn.Module so optimizer.step() updates are visible.
        if self._dmc_provider is None:
            from training.core.actor.network_provider import LocalNetworkProvider
            from training.paradigms.dmc.inference_net import DMCInferenceNet

            infer_net = DMCInferenceNet(self.agent.net).to(self.agent.device).eval()
            self._dmc_provider = LocalNetworkProvider(infer_net, device=str(self.agent.device))
        return self._dmc_provider

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

# Module-level per-actor episode counter; child processes get their own
# copy after spawn so streams are independent.
_DMC_ACTOR_EP_SEQ: dict = {}


def _resolve_paradigm_factory(cfg: Any, key: str) -> Any:
    """Look up a dotted ``module.attr`` factory path in cfg.paradigm
    + import it. Raises ValueError loudly when missing (CS4)."""
    from training.core.actor.actor_process import resolve_builder

    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    path = pdict.get(key)
    if not path:
        raise ValueError(
            f'DMC mp actor: cfg.paradigm.{key} required for spawn (dotted "module.attr").',
        )
    return resolve_builder(path)


def _dmc_build_env_factory(cfg: Any, seed: int):
    return _resolve_paradigm_factory(cfg, 'mp_env_factory_path')(cfg, seed)


def _dmc_build_opp_registry(cfg: Any):
    return _resolve_paradigm_factory(cfg, 'mp_opp_registry_path')(cfg)


def _dmc_build_policy(cfg: Any, actor_id: int):
    from training.paradigms.dmc.config import DMCParadigmConfig
    from training.paradigms.dmc.policy import DMCEpisodePolicy

    pcfg = DMCParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
    return DMCEpisodePolicy(
        epsilon=pcfg.epsilon,
        seed=int(cfg.meta.seed) + 11 + actor_id,
        deterministic=False,
    )


def _dmc_build_provider(cfg: Any, actor_id: int):
    return _resolve_paradigm_factory(cfg, 'mp_provider_path')(cfg, actor_id)


def _dmc_spec_sampler(cfg: Any, actor_id: int):
    from training.core.protocols import EpisodeSpec

    _DMC_ACTOR_EP_SEQ[actor_id] = _DMC_ACTOR_EP_SEQ.get(actor_id, 0) + 1
    seed = derive_seed(int(cfg.meta.seed), 'mp_ep', actor_id, _DMC_ACTOR_EP_SEQ[actor_id])
    return EpisodeSpec(scenario_seed=seed, opponent_id='random')


class DMCMultiProcessCollector:
    """DMC async collector — N actor procs + SHM ring + WeightsSHM.
    ``collect`` drains the ring; ``sync_weights`` re-publishes; ``close``
    terminates. Production use needs DmcAgent → typed-EpisodePolicy."""

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        opp_pool: Any,
        env_factory: Any,
        *,
        runtime: Optional[Runtime] = None,
        ring: Optional[SHMRing] = None,
    ) -> None:
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self.opp_pool = opp_pool
        self.env_factory = env_factory
        self._master_seed = int(cfg.meta.seed)
        self._episode_seq = 0
        self._weights_version = 0
        self.runtime = runtime if runtime is not None else Runtime(cfg)
        self.ring = ring if ring is not None else SHMRing(capacity=1024, slot_payload_max=512 * 1024)
        self._spawned = False

    def _bootstrap(self) -> None:
        """One-shot: publish initial weights then spawn actors. Idempotent."""
        if self._spawned:
            return
        # W3a constraint: parent must publish('latest') before workers attach.
        sd_cpu = {k: v.detach().cpu() for k, v in self.network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        n_actors = int(getattr(self.cfg.pipeline, 'num_actors', 1))
        actor_kwargs = {
            'build_env_factory_path': 'training.paradigms.dmc.collector._dmc_build_env_factory',
            'build_opp_registry_path': 'training.paradigms.dmc.collector._dmc_build_opp_registry',
            'build_policy_path': 'training.paradigms.dmc.collector._dmc_build_policy',
            'build_provider_path': 'training.paradigms.dmc.collector._dmc_build_provider',
            'spec_sampler_path': 'training.paradigms.dmc.collector._dmc_spec_sampler',
            'transition_queue': self.ring,
        }
        self.runtime.start_actors(n_actors=n_actors, actor_kwargs_factory=lambda i: dict(actor_kwargs))
        self._spawned = True

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Drain SHM ring → CollectorOutput. ``n_episodes`` = max
        actor-pushed records to pull this iter; actors run continuously
        between drains."""
        del provider  # mp mode: actors own their own providers
        self._bootstrap()
        episodes_for_buffer: list = []
        episode_stats: list = []
        n_trans_total = 0
        n_pulled = 0
        max_pull = max(1, int(n_episodes))
        while n_pulled < max_pull:
            item = self.ring.try_pop()
            if item is None:
                break
            self._episode_seq += 1
            n_trans = len(item) if hasattr(item, '__len__') else 0
            episodes_for_buffer.append((item, None))
            n_trans_total += n_trans
            episode_stats.append({'ep_idx': self._episode_seq, 'n_transitions': n_trans, 'source': 'mp_actor'})
            n_pulled += 1
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'dmc_episodes': episodes_for_buffer, 'n_pulled': n_pulled},
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Publish latest learner weights to WeightsSHM. Actor providers
        poll between episodes (see actor_main)."""
        self._weights_version += 1
        sd_cpu = {k: v.detach().cpu() for k, v in network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        return self._weights_version

    def close(self) -> None:
        try:
            self.runtime.close()
        except Exception:
            pass
        try:
            self.ring.close()
        except Exception:
            pass
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


# Public alias per FU-W3b-DMC task spec.
DMCAsyncCollector = DMCMultiProcessCollector
