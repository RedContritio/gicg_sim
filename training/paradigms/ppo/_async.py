"""PPOAsyncCollector — FU-W3b-PPO 真 mp 接通(走 W3a core/actor)。

Split from collector.py for line-limit;public 入口仍 collector.PPOAsyncCollector
(re-export)。N actor 各跑 episode(EpisodeRunner + PPOEpisodePolicy +
LocalNetworkProvider);IPCQueue 流回 learner;collect() drain + GAE;
sync_weights() 通过 WeightsSHM 广播。

W3a 约束:LocalNetworkProvider per actor、WeightsSHM publish 在 spawn 前、
network device='cpu' 再 pickle、无 Manager()。跨 spawn 边界:tempfile pickle
+ env var(spawn 子进程继承 env)— 不触 core/actor.actor_main 签名。

PPO frozen tier(per ADR-0008):简单接通。Driver 应每次 train 后调
sync_weights — PPO strict on-policy。
"""

from __future__ import annotations

import os
import pickle
import random
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from training.core.protocols import CollectorOutput, EpisodeSpec, Transition
from training.paradigms.ppo.policy import PPOEpisodePolicy, compute_gae

_ENV_SHM_PATH = 'GICG_PPO_W3B_SHM_PATH'
_ENV_NET_PATH = 'GICG_PPO_W3B_NET_PATH'
_ENV_OPPONENT = 'GICG_PPO_W3B_OPPONENT'


def _derive_seed(master_seed: int, *labels: Any) -> int:
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        for b in repr(lab).encode('utf-8'):
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


# ---------- spawn-safe top-level builders(actor_main resolves via dotted path) ---------- #


def build_env_factory(cfg: Any, seed: int):
    del seed
    from gicg_env import GicgEnv

    scen = cfg.scenario
    fd = list(scen.fix_dice) if getattr(scen, 'fix_dice', None) else None

    def _factory(scenario_seed: int):
        env = GicgEnv(
            list(scen.team_0),
            list(scen.team_1),
            card_pool=list(getattr(scen, 'card_pool', None) or ()),
            seed=int(scenario_seed),
            data_dir=str(getattr(scen, 'data_dir', 'data')),
            max_rounds=int(getattr(scen, 'max_rounds', 3)),
            fix_dice=fd,
            deck_padding=getattr(scen, 'deck_padding', None),
            pool=getattr(scen, 'pool', ['v_legacy', 'test_basic']),
        )
        env.reset(seed=int(scenario_seed))
        return env

    return _factory


def build_opp_registry(cfg: Any):
    # Frozen tier:只接 random baseline(完整 F1-D2 在 legacy/rollout.py)。
    del cfg
    from training.core.eval.baselines import OpponentRegistry

    def _mk(seed, params):
        del params
        rng = random.Random(int(seed))

        class _R:
            def select_action(self, env):
                kinds, _ = env.get_legal_actions() if hasattr(env, 'get_legal_actions') else ([0], None)
                return rng.choice(list(kinds)) if kinds else 0

        return _R()

    reg = OpponentRegistry()
    extra = os.environ.get(_ENV_OPPONENT, 'random')
    for tag in {'rollout', 'random', 'self', extra}:
        reg.register(tag, _mk)
    return reg


def build_policy(cfg: Any, actor_id: int):
    pcfg = dict(cfg.paradigm) if hasattr(cfg, 'paradigm') else {}
    return PPOEpisodePolicy(
        gamma=float(pcfg.get('gamma', 0.99)),
        gae_lambda=float(pcfg.get('gae_lambda', 0.95)),
        seed=int(cfg.meta.seed) + 1000 + int(actor_id),
        deterministic=False,
    )


def build_provider(cfg: Any, actor_id: int):
    # env var → tempfile → WeightsSHM.attach → LocalNetworkProvider 包装。
    del cfg, actor_id
    shm_path = os.environ.get(_ENV_SHM_PATH)
    net_path = os.environ.get(_ENV_NET_PATH)
    if not shm_path or not net_path:
        raise RuntimeError(f'PPOAsync handoff missing: set {_ENV_SHM_PATH}/{_ENV_NET_PATH} before spawn')
    from training.core.actor.network_provider import LocalNetworkProvider
    from training.core.actor.weights_shm import WeightsSHM

    with open(shm_path, 'rb') as f:
        shm_info = pickle.load(f)
    with open(net_path, 'rb') as f:
        network = pickle.load(f)
    shm = WeightsSHM.attach(shm_info)
    sd, version = shm.read('latest')
    if sd is None:
        raise RuntimeError('PPOAsync: WeightsSHM latest cold — publish before spawn')
    network.load_state_dict(sd)
    network.eval()
    local = LocalNetworkProvider(network, device='cpu', version_tag='latest')
    local.version = int(version)
    return _PPOActorProvider(local, shm)


_SPEC_COUNTERS: dict = {}


def spec_sampler(cfg: Any, actor_id: int) -> EpisodeSpec:
    seq = _SPEC_COUNTERS.get(actor_id, 0)
    _SPEC_COUNTERS[actor_id] = seq + 1
    seed = _derive_seed(int(cfg.meta.seed), 'actor', int(actor_id), 'episode', int(seq))
    opp = os.environ.get(_ENV_OPPONENT, 'random')
    return EpisodeSpec(scenario_seed=int(seed), opponent_id='random' if opp == 'self' else opp)


class _PPOActorProvider:
    """LocalNetworkProvider + WeightsSHM:update_weights 从 SHM 读 latest。"""

    def __init__(self, local_provider, shm) -> None:
        self._local = local_provider
        self._shm = shm

    def forward(self, obs: Any, mask: Any) -> Any:
        return self._local.forward(obs, mask)

    def update_weights(self, version_tag: str = 'latest', state_dict: dict = None) -> int:
        if state_dict is not None:
            return self._local.update_weights(state_dict=state_dict)
        sd, ver = self._shm.read(version_tag)
        if sd is not None and ver > self._local.current_version():
            self._local.network.load_state_dict(sd)
            self._local.version = int(ver)
        return self._local.current_version()

    def current_version(self) -> int:
        return self._local.current_version()

    def close(self) -> None:
        self._local.close()


class PPOAsyncCollector:
    """N actor real mp via W3a core/actor。env_factory 兼容签名但 async 不用
    (actor 子进程通过 build_env_factory 从 cfg.scenario 重建)。"""

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
        # tempfile pickle handoff:network blueprint(.cpu()) + SHM info。
        self._tmpdir = Path(tempfile.mkdtemp(prefix='gicg_ppo_w3b_'))
        np_path, sp_path = self._tmpdir / 'net.pkl', self._tmpdir / 'shm.pkl'
        with open(np_path, 'wb') as f:
            pickle.dump(network.cpu(), f, protocol=pickle.HIGHEST_PROTOCOL)
        with open(sp_path, 'wb') as f:
            pickle.dump(self._weights_shm.serialize_for_worker(['latest']), f, protocol=pickle.HIGHEST_PROTOCOL)
        os.environ[_ENV_SHM_PATH], os.environ[_ENV_NET_PATH] = str(sp_path), str(np_path)
        os.environ[_ENV_OPPONENT] = str(paradigm_cfg.rollout.rollout_opponent)

        self._queue = IPCQueue(maxsize=max(256, n_actors * int(paradigm_cfg.rollout.n_games_per_iter) * 2))
        self._runtime = Runtime(cfg, weights_shm=self._weights_shm)
        m = 'training.paradigms.ppo._async'
        kw = {f'build_{k}_path': f'{m}.build_{k}' for k in ('env_factory', 'opp_registry', 'policy', 'provider')}
        kw['spec_sampler_path'] = f'{m}.spec_sampler'
        kw['transition_queue'] = self._queue
        self._runtime.start_actors(n_actors=n_actors, actor_kwargs_factory=lambda i: dict(kw))

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
        for var in (_ENV_SHM_PATH, _ENV_NET_PATH, _ENV_OPPONENT):
            os.environ.pop(var, None)

    def state_dict(self) -> dict:
        return {'iter_seq': self._iter_seq, 'master_seed': self._master_seed, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._iter_seq = int(sd.get('iter_seq', 0))
        self._master_seed = int(sd.get('master_seed', self._master_seed))
        self._weights_version = int(sd.get('weights_version', self._weights_version))
