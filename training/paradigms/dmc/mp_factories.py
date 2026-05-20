"""DMC mp-mode factories — env, opp registry, provider.

Wired into spawned actors via ``DMCMultiProcessCollector._bootstrap``:
parent constructs a shared :class:`InferenceServer` (one per collector),
attaches N :class:`InferenceClient` handles, and threads each client to
the corresponding actor through the ``inference_client`` kwarg.

Provider factory: returns :class:`_DMCObsDictRemoteProvider`, a thin
adapter that owns a per-actor :class:`DmcAgent` for env-side static
caching + 15-tensor obs encoding (mirroring
``DMCSerialCollector._ensure_dmc_provider``) and forwards the encoded
obs_dict to the shared inference server via the supplied client.
LocalNetworkProvider fallback is intentionally absent — for serial mode
callers must use ``DMCSerialCollector`` directly.

The factories live in their own module (not ``collector.py``) so the
collector module stays focused on collect/sync loops and so the spawn
target's import surface is minimal.
"""

from __future__ import annotations

from typing import Any

import torch


def build_dmc_env_factory(cfg: Any, seed: int):
    """Return callable(scenario_seed) -> GicgEnv suitable for the actor
    process. Mirrors ``training.core.env_factory.make_env_factory``; the
    seed argument forwarded by the actor scheduler becomes the master
    seed for this actor's env stream.
    """
    from training.core.env_factory import make_env_factory

    return make_env_factory(cfg, None, master_seed=seed)


def build_dmc_opp_registry(cfg: Any):
    """Return :class:`OpponentRegistry` covering the opponent IDs that
    ``_dmc_spec_sampler`` can emit. P2-PoC restricts spec_sampler to
    ``opponent_id='random'`` (greedy / historical would require sharing
    learner weights across processes — out of scope).
    """
    from training.core.eval.baselines import OpponentRegistry
    from training.paradigms.dmc._opponent import RandomPlayer

    reg = OpponentRegistry()
    reg.register('random', lambda seed=0, params=None: RandomPlayer(seed=int(seed or 0)))
    return reg


class _DMCObsDictRemoteProvider:
    """Per-actor provider routing DMC's 15-tensor obs_dict to a shared
    :class:`InferenceServer` via :class:`InferenceClient`.

    The :class:`EpisodeRunner` contract is ``policy.act(obs, mask,
    provider)``; obs is the raw ``env._get_obs()`` ndarray, not the
    obs_dict that :class:`DMCInferenceNet` expects. This provider closes
    the gap by owning a private :class:`DmcAgent` instance that caches
    per-episode static fields (via ``game_start``) and encodes each turn's
    dyn_obs into the full 15-tensor dict before sending it to the server.

    ``forward(obs, mask)`` rebuilds the obs_dict from the env reference
    cached at ``observe_env`` time; callers that bypass ``observe_env``
    fall back to building a minimal stub from the raw ndarray, which
    will fail loudly on the server side — that is intentional per CS4.

    Buffer-side obs capture: ``forward`` ALSO computes the numpy-form
    obs_dict via :func:`capture_obs` and stashes it on
    ``self.last_obs_dict``. :class:`DMCEpisodePolicy` reads this back
    into ``meta['dmc_obs_dict']`` so the collector can reconstruct a
    proper :class:`DmcTransition` from each pushed transition. The two
    obs_dict variants are not the same shape — server side wants
    batched torch tensors via ``DmcAgent.build_obs_dict``; buffer side
    wants squeezed numpy arrays via ``capture_obs``. Both run once per
    actor step; ``capture_obs`` is cheap (numpy reshapes only).
    """

    transition_schema = 'dmc_transition'

    def __init__(self, cfg: Any, actor_id: int, client: Any) -> None:
        from training.paradigms.dmc._agent import DmcAgent
        from training.paradigms.dmc.config import DMCParadigmConfig

        self.cfg = cfg
        self.actor_id = actor_id
        self.client = client
        pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
        pcfg = DMCParadigmConfig.from_dict(pdict)
        # Agent lives on cpu — only its parameters are used for obs
        # encoding (counter_sids / hook_emb / etc. caches). Network
        # forward never runs on this side; the server owns weights.
        self.agent = DmcAgent(
            cfg=pcfg.agent,
            device='cpu',
            lr=pcfg.lr,
            weight_decay=pcfg.weight_decay,
            epsilon=0.0,  # exploration owned by DMCEpisodePolicy
        )
        self._env_ref: Any = None
        self._last_static_id: int = -1
        self.version = 0
        # Buffer-side obs cache — populated each forward() so the
        # collector can rehydrate DmcTransition from the actor push.
        self.last_obs_dict: Any = None

    def observe_env(self, env: Any) -> None:
        """Called by the actor loop hook before each policy.act to cache
        the env reference + (re-)trigger DmcAgent.game_start when a new
        episode begins. Detects fresh episodes via env._engine identity.
        """
        self._env_ref = env
        eid = id(getattr(env, '_engine', env))
        if eid != self._last_static_id:
            static_obs = env.static_obs if hasattr(env, 'static_obs') else env._get_static_obs()
            self.agent.game_start(static_obs)
            self._last_static_id = eid

    def forward(self, obs: Any, mask: Any) -> Any:
        if self._env_ref is None:
            raise RuntimeError(
                '_DMCObsDictRemoteProvider.forward: observe_env(env) must be called per turn '
                'before policy.act so the obs_dict can be encoded with cached static fields.'
            )
        # Buffer-side: numpy obs_dict for DmcTransition reconstruction.
        # Done BEFORE the server request so a server-side exception still
        # leaves a valid obs cached for the next turn's debug trail.
        from training.paradigms.dmc._episode import capture_obs

        self.last_obs_dict = capture_obs(self._env_ref, self.agent)
        # Server-side: torch obs_dict for DMCInferenceNet.forward.
        obs_dict = self.agent.build_obs_dict(self._env_ref)
        # Server returns the raw q tensor (shape (1, max_actions)).
        out = self.client.request(obs_dict, None)
        # Match the DmcAgent return contract: 'q' head dict.
        if isinstance(out, torch.Tensor):
            return {'logit_as_q': out[0]}
        return out

    def update_weights(self, version_tag: Any = None, state_dict: Any = None) -> int:
        # Server owns weights — no-op on the actor side.
        return self.version

    def current_version(self) -> int:
        return self.version

    def device(self) -> torch.device:
        if hasattr(self.client, 'server_device'):
            return torch.device(self.client.server_device())
        return torch.device('cpu')

    def close(self) -> None:
        if hasattr(self.client, 'close'):
            try:
                self.client.close()
            except Exception:
                pass


def build_dmc_provider(cfg: Any, actor_id: int, *, inference_client: Any = None) -> Any:
    """Return a per-actor remote provider wired to the shared inference
    server. ``inference_client`` is REQUIRED — parent process must have
    constructed + registered it before spawning this actor. Missing
    client raises loudly (CS4 strict): there is no LocalNetworkProvider
    fallback in mp mode; serial mode owns its own provider via
    ``DMCSerialCollector._ensure_dmc_provider``.
    """
    if inference_client is None:
        raise ValueError(
            f'build_dmc_provider[actor_id={actor_id}]: inference_client kwarg required — '
            f'parent DMCMultiProcessCollector._bootstrap must register a client per actor '
            f'and pass it via actor_kwargs_factory.'
        )
    return _DMCObsDictRemoteProvider(cfg=cfg, actor_id=actor_id, client=inference_client)
