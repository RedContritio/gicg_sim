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

    dbg = getattr(cfg, 'debug', None)
    server = InferenceServer(
        DMCInferenceNet(actor_critic),
        device=device,
        max_batch=max(1, n_actors),
        # Decode-offload (2026-05-20): actor ships numpy payload, server
        # decoder reuses live hook_encoder for static encoding + per-turn
        # tensor materialisation. See module docstring of
        # `training.paradigms.dmc.mp_factories`.
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        stats_q=stats_q,
        stats_interval_s=5.0,
        perf_trace_enabled=bool(getattr(dbg, 'perf_trace', False)) if dbg else False,
        perf_trace_flush_n=int(getattr(dbg, 'perf_trace_flush_n', 200)) if dbg else 200,
        perf_trace_flush_s=float(getattr(dbg, 'perf_trace_flush_s', 1.0)) if dbg else 1.0,
        perf_trace_dir=getattr(dbg, 'perf_trace_dir', None) if dbg else None,
    )
    clients = [InferenceClient.attach_to_server(server, timeout_ms=30000) for _ in range(n_actors)]
    server.start(wait_ready_s=30.0)
    return server, clients


def _dmc_spec_sampler(cfg: Any, actor_id: int):
    """Sample one :class:`EpisodeSpec` per call。

    R6.3 (2026-05-25): opponent_id 从 hardcoded ``'random'`` 改为
    ``cfg.paradigm['opponent_mix']`` weighted sampling (random / f1d2 /
    f1d4 keys; weights are sampled per-call with a per-actor RNG seeded
    from the run seed)。 ``historical`` 权重在 mp path silently dropped
    (mp_factories.py 不注册 historical — Python端 ckpt ring 跨 mp.Manager
    不可行),剩余权重 re-normalized over (random / f1d2 / f1d4)。 若 weight
    dict 缺失/空 → fallback to 100% ``'random'`` (preserves原 P2-PoC
    behavior for cfgs without opponent_mix set)。
    """
    import random as _random

    from training.core.protocols import EpisodeSpec

    # Late import avoids a circular import at module load time
    # (collector → _mp_internal → derive_seed lives in collector).
    from training.paradigms.dmc.collector import derive_seed

    _DMC_ACTOR_EP_SEQ[actor_id] = _DMC_ACTOR_EP_SEQ.get(actor_id, 0) + 1
    ep_seq = _DMC_ACTOR_EP_SEQ[actor_id]
    seed = derive_seed(int(cfg.meta.seed), 'mp_ep', actor_id, ep_seq)
    opp_id = _sample_opponent_id(cfg, actor_id, ep_seq)
    return EpisodeSpec(scenario_seed=seed, opponent_id=opp_id)


def _sample_opponent_id(cfg: Any, actor_id: int, ep_seq: int) -> str:
    """Weighted sample opponent_id from cfg.paradigm['opponent_mix']。

    Only ``random``/``f1d2``/``f1d4`` are sampleable (mp_factories.py
    registers exactly these); ``historical`` weight (if present) is
    silently dropped and remaining weights are re-normalized。 若
    paradigm dict 缺 opponent_mix 或 dict 空 → return ``'random'``
    (preserves P2-PoC fallback for legacy cfg)。

    Determinism:每次 call 用 (run_seed, actor_id, ep_seq) tuple 作 RNG
    seed,actor-level reproducible(同 seed 同 episode 序号产同 opp 序列)。
    """
    import random as _random

    from training.paradigms.dmc.collector import derive_seed

    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    omix = pdict.get('opponent_mix') or {}
    if not omix:
        return 'random'
    # Drop historical (not registered in mp_factories.py per module docstring).
    samplable = {k: float(v) for k, v in omix.items() if k in ('random', 'f1d2', 'f1d4') and float(v) > 0.0}
    if not samplable:
        return 'random'
    # Re-normalize over samplable subset (historical weight redistributed proportionally).
    total = sum(samplable.values())
    keys = list(samplable.keys())
    weights = [samplable[k] / total for k in keys]
    rng_seed = derive_seed(int(cfg.meta.seed), 'opp_sample', actor_id, ep_seq)
    rng = _random.Random(rng_seed)
    return rng.choices(keys, weights=weights, k=1)[0]


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
    """Reject truncated/unknown records before they enter the DMC buffer."""
    from training.core.matchup.outcome import terminal_outcome

    return float(terminal_outcome(winner, our_player))
