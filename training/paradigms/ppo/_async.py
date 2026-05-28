"""PPOAsyncCollector — FU-W3b-PPO 真 mp 接通(走 W3a core/actor)。

Split from collector.py for line-limit; public 入口仍 collector.PPOAsyncCollector
(re-export)。N actor 各跑 episode (EpisodeRunner + PPOEpisodePolicy +
LocalNetworkProvider);IPCQueue 流回 learner;collect() drain + GAE;
sync_weights() 通过 WeightsSHM 广播。

**Spawn handoff** (post 2026-05-29 / I31 backlog #88 cleanup):

W3a-era env-var bridge (``_ENV_SHM_PATH`` / ``_ENV_NET_PATH`` / ``_ENV_OPPONENT``)
deleted — replaced with AB13 ``provider_kwargs`` escape hatch. Parent passes
``WeightsSHM.serialize_for_worker`` returned dict + network blueprint
tempfile path str through ``actor_kwargs_factory`` → ``actor_main`` →
``mp_factories.build_provider(**provider_kwargs)``. ``opp_id`` is read
directly from cfg (auto-pickled by mp spawn ctx, no env bridge).

Builders + provider class moved to ``training.paradigms.ppo.mp_factories``;
dotted-path strings in this module point at the new home.

PPO frozen tier (per ADR-0008):简单接通。Driver 应每次 train 后调
sync_weights — PPO strict on-policy。
"""

from __future__ import annotations

import pickle
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from training.core.protocols import CollectorOutput, Transition
from training.paradigms.ppo.policy import compute_gae


class PPOAsyncCollector:
    """N actor real mp via W3a core/actor。env_factory 兼容签名但 async 不用
    (actor 子进程通过 mp_factories.build_env_factory 从 cfg.scenario 重建)。"""

    requires_network_in_collect = True
    _drain_timeout_s: float = 60.0

    def __init__(self, cfg: Any, paradigm_cfg: Any, network: Any, env_factory: Any = None) -> None:
        del env_factory
        from training.core.actor.ipc.queue import IPCQueue
        from training.core.actor.runtime import Runtime
        from training.core.actor.weights_shm import WeightsSHM

        n_actors = int(getattr(cfg.pipeline, 'num_actors', 1))
        if n_actors < 1:
            raise ValueError(f'PPOAsyncCollector: num_actors must be ≥ 1, got {n_actors}')

        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self._master_seed = int(cfg.meta.seed)
        self._iter_seq = 0
        self._n_actors = n_actors
        self._closed = False

        nb = sum(t.numel() * t.element_size() for t in network.state_dict().values())
        # SHM size:2x state_dict + 16KB margin, floor 64MiB。W3a #2 publish 在 spawn 前。
        self._weights_shm = WeightsSHM(max_state_dict_bytes=max(64 * 1024 * 1024, 2 * nb + 16384), owner=True)
        self._weights_version = 1
        self._publish_network(network, version=1)

        # Spawn-safe handoff bundle (post-cleanup AB13 provider_kwargs path):
        # WeightsSHM info pickles via _SHMSlot.__getstate__ (name + Lock),
        # child re-attaches via WeightsSHM.attach. Network blueprint still
        # goes through tempfile pickle — frozen-tier LocalNetworkProvider
        # design doesn't introduce InferenceServer.
        weights_shm_info = self._weights_shm.serialize_for_worker(['latest'])
        self._tmpdir = Path(tempfile.mkdtemp(prefix='gicg_ppo_w3b_'))
        np_path = self._tmpdir / 'net.pkl'
        with open(np_path, 'wb') as f:
            pickle.dump(network.cpu(), f, protocol=pickle.HIGHEST_PROTOCOL)
        network_blueprint_path = str(np_path)

        self._queue = IPCQueue(maxsize=max(256, n_actors * int(paradigm_cfg.rollout.n_games_per_iter) * 2))
        self._runtime = Runtime(cfg, weights_shm=self._weights_shm)
        m = 'training.paradigms.ppo.mp_factories'
        kw = {f'build_{k}_path': f'{m}.build_{k}' for k in ('env_factory', 'opp_registry', 'policy', 'provider')}
        kw['spec_sampler_path'] = f'{m}.spec_sampler'
        kw['transition_queue'] = self._queue
        self._runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda i: dict(
                kw,
                provider_kwargs={
                    'weights_shm_info': weights_shm_info,
                    'network_blueprint_path': network_blueprint_path,
                },
            ),
        )

    def _publish_network(self, network: Any, version: int) -> None:
        # W3a #3:写 SHM 前 .cpu() state_dict。
        sd = {k: v.detach().cpu() for k, v in network.state_dict().items()}
        self._weights_shm.write('latest', sd, version=int(version))

    def collect(self, n_units: int, provider: Any) -> CollectorOutput:
        """Drain queue 到 target_n_episodes(n_units 解释为 n_games,0 → pcfg
        rollout.n_games_per_iter)。provider ignored — actor 自有 provider。"""
        del provider
        self._iter_seq += 1
        target = int(n_units) if n_units > 0 else int(self.pcfg.rollout.n_games_per_iter)
        transitions: list = []
        episode_stats: list = []
        n_drained = 0
        n_trans = 0
        deadline = time.time() + self._drain_timeout_s
        while n_drained < target and time.time() < deadline:
            try:
                item = self._queue.get(timeout=0.5)
            except Exception:
                continue
            if not item:
                continue
            T = len(item)
            rewards = np.array([float(t.reward) for t in item], dtype=np.float32)
            values = np.array([float(t.payload.get('value', 0.0)) for t in item], dtype=np.float32)
            dones = np.array([bool(t.done) for t in item], dtype=bool)
            # Force last-step done so GAE bootstrap V=0(timeout 路径保守 estimator)。
            if not dones[-1]:
                dones = dones.copy()
                dones[-1] = True
            advs, rets = compute_gae(rewards, values, dones, self.pcfg.gamma, self.pcfg.gae_lambda)
            for i, src in enumerate(item):
                pl = dict(src.payload)
                pl['advantage'], pl['return'] = float(advs[i]), float(rets[i])
                transitions.append(
                    Transition(
                        obs=src.obs,
                        action=int(src.action),
                        legal_mask=src.legal_mask,
                        reward=float(src.reward),
                        done=bool(dones[i]),
                        payload=pl,
                    )
                )
            episode_stats.append({'iter_seq': self._iter_seq, 'n_transitions': T, 'final_reward': float(rewards[-1])})
            n_drained += 1
            n_trans += T
        return CollectorOutput(
            transitions=transitions,
            episode_stats=episode_stats,
            runtime_metrics={
                'n_episodes_drained': n_drained,
                'target_n_episodes': target,
                'weights_version': self._weights_version,
            },
            n_units=n_trans,
        )

    def sync_weights(self, network: Any) -> None:
        # Publish 新 weights;actor 每 episode 间隙 provider.update_weights pick up。
        self._weights_version += 1
        self._publish_network(network, version=self._weights_version)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        import shutil

        for fn in (self._runtime.close, self._queue.close, lambda: shutil.rmtree(self._tmpdir, ignore_errors=True)):
            try:
                fn()
            except Exception:
                pass

    def state_dict(self) -> dict:
        return {'iter_seq': self._iter_seq, 'master_seed': self._master_seed, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._iter_seq = int(sd.get('iter_seq', 0))
        self._master_seed = int(sd.get('master_seed', self._master_seed))
        self._weights_version = int(sd.get('weights_version', self._weights_version))
