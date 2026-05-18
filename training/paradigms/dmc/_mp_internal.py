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


def _spawn_inference_pool(cfg: Any, network: Any, n_actors: int) -> tuple:
    from training.core.actor.inference_client import InferenceClient
    from training.core.actor.inference_server import InferenceServer
    from training.paradigms.dmc.inference_net import DMCInferenceNet

    device = str(getattr(cfg.meta, 'device', 'cpu'))
    actor_critic = network.agent.net if hasattr(network, 'agent') else network
    server = InferenceServer(DMCInferenceNet(actor_critic), device=device, max_batch=max(1, n_actors))
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
