"""DMC mp-mode internal helpers used by :class:`DMCMultiProcessCollector`.

Split out of ``collector.py`` to stay under the 300-line cap. Holds:

- ``_dmc_build_*`` legacy resolvers (re-exported from ``collector``)
- ``_spawn_inference_pool`` parent-side server + client construction
- ``_dmc_spec_sampler`` per-actor episode-spec sampler

The actor-side factories themselves live in
:mod:`training.paradigms.dmc.mp_factories` (E target / P2-PoC wiring);
this module only holds the dispatch glue.
"""

from __future__ import annotations

from typing import Any

# Per-actor episode counter; child processes copy after spawn.
_DMC_ACTOR_EP_SEQ: dict = {}


def _resolve_paradigm_factory(cfg: Any, key: str) -> Any:
    """Look up dotted ``module.attr`` factory path in cfg.paradigm (CS4)."""
    from training.core.actor.actor_process import resolve_builder

    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    path = pdict.get(key)
    if not path:
        raise ValueError(f'DMC mp actor: cfg.paradigm.{key} required for spawn (dotted "module.attr").')
    return resolve_builder(path)


def _dmc_build_env_factory(cfg: Any, seed: int):
    return _resolve_paradigm_factory(cfg, 'mp_env_factory_path')(cfg, seed)


def _dmc_build_opp_registry(cfg: Any):
    return _resolve_paradigm_factory(cfg, 'mp_opp_registry_path')(cfg)


def _dmc_build_policy(cfg: Any, actor_id: int):
    from training.paradigms.dmc.config import DMCParadigmConfig
    from training.paradigms.dmc.policy import DMCEpisodePolicy

    pcfg = DMCParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
    return DMCEpisodePolicy(epsilon=pcfg.epsilon, seed=int(cfg.meta.seed) + 11 + actor_id, deterministic=False)


def _dmc_build_provider(cfg: Any, actor_id: int):
    return _resolve_paradigm_factory(cfg, 'mp_provider_path')(cfg, actor_id)


def _spawn_inference_pool(cfg: Any, network: Any, n_actors: int, metrics_logger: Any = None) -> tuple:
    from training.core.actor._mp_helpers import get_ctx
    from training.core.actor.inference_client import InferenceClient
    from training.core.actor.inference_server import InferenceServer
    from training.paradigms.dmc.inference_net import DMCInferenceNet

    device = str(getattr(cfg.meta, 'device', 'cpu'))
    actor_critic = network.agent.net if hasattr(network, 'agent') else network

    # Stats wiring — 创建 cross-process queue 给 InfServer push 周期 aggregate
    # 数据,master logger drainer thread 读 + log kind="inf_server" 行入
    # metrics.jsonl(实测 perf 瓶颈位置的关键信号:queue_depth_avg /
    # batching_efficiency / process_ms_avg)。
    stats_q = None
    if metrics_logger is not None:
        stats_q = get_ctx().Queue(maxsize=1024)
        metrics_logger.attach_external_queue(stats_q, name='inf_server')

    server = InferenceServer(
        DMCInferenceNet(actor_critic),
        device=device,
        max_batch=max(1, n_actors),
        # Decode-offload (2026-05-20): actor ships numpy payload, server
        # decoder reuses live hook_encoder for static encoding + per-turn
        # tensor materialisation. See module docstring of
        # `training.paradigms.dmc.mp_factories`.
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        # Batched decode (2026-05-21):一次 numpy stack + 1 次 H2D /
        # tensor 替代 N×串行 decode。production Win N=16 实测前 decode 占
        # InfServer wall 69.6% (35.7 ms / batch),batched 化降到预估
        # 5-8 ms。 server 优先走 batched 路径,失败 fall back single decode。
        batched_request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_requests',
        stats_q=stats_q,
        stats_interval_s=5.0,
    )
    clients = [InferenceClient.attach_to_server(server, timeout_ms=30000) for _ in range(n_actors)]
    server.start(wait_ready_s=30.0)
    return server, clients


def _dmc_spec_sampler(cfg: Any, actor_id: int):
    from training.core.protocols import EpisodeSpec

    # Late import avoids a circular import at module load time
    # (collector → _mp_internal → derive_seed lives in collector).
    from training.paradigms.dmc.collector import derive_seed

    _DMC_ACTOR_EP_SEQ[actor_id] = _DMC_ACTOR_EP_SEQ.get(actor_id, 0) + 1
    seed = derive_seed(int(cfg.meta.seed), 'mp_ep', actor_id, _DMC_ACTOR_EP_SEQ[actor_id])
    return EpisodeSpec(scenario_seed=seed, opponent_id='random')


def _adapt_episode_record(record: Any) -> tuple[list, int]:
    """Convert core :class:`EpisodeRecord` (list[Transition] + winner)
    pulled off the SHM ring into list[:class:`DmcTransition`] for the
    DMC buffer. Returns ``(dmc_transitions, n_dropped)`` where dropped
    counts transitions missing ``payload['dmc_obs_dict']`` — defensive,
    since :class:`_DMCObsDictRemoteProvider` populates it on every
    ``forward`` and ``observe_env`` fires before each ``policy.act`` in
    :class:`EpisodeRunner`. A non-zero count is a wiring bug worth
    surfacing on metrics, not silently swallowed.
    """
    # Late import: buffer → core.protocols → numpy stack — fine here
    # since this runs at collect time, not module load.
    from training.paradigms.dmc.buffer import DmcTransition

    dmc_transitions: list = []
    n_dropped = 0
    transitions = getattr(record, 'transitions', record)  # tolerate raw list
    for t in transitions:
        payload = getattr(t, 'payload', None) or {}
        obs_dict = payload.get('dmc_obs_dict')
        if obs_dict is None:
            n_dropped += 1
            continue
        dmc_transitions.append(DmcTransition(obs_dict=obs_dict, action_idx=int(t.action), G=0.0))
    return dmc_transitions, n_dropped


def _terminal_z(winner: int, our_player: int) -> float:
    """Mirror :func:`training.paradigms.dmc._episode.terminal_z` —
    +1 win, -1 lose, 0 draw / unknown. Inlined to avoid pulling
    :mod:`_episode` at collector load (cycle with buffer.py)."""
    if winner is None or winner < 0:
        return 0.0
    if winner == our_player:
        return 1.0
    if winner == 2:  # draw sentinel
        return 0.0
    return -1.0
