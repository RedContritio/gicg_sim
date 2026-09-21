"""Process and inference bootstrap for the AZ async collector."""

from __future__ import annotations


def bootstrap(collector) -> None:
    if collector._spawned:
        return

    from training.paradigms.az._async import RING_TAG, WEIGHTS_TAG, _cpu_net_state_dict
    from training.paradigms.az.config import AZParadigmConfig

    pcfg = collector.pcfg
    if pcfg is None or not hasattr(pcfg, 'agent'):
        pcfg = AZParadigmConfig.from_dict(collector.cfg.paradigm if isinstance(collector.cfg.paradigm, dict) else {})
    local = bool(getattr(pcfg, 'local_inference', True))
    n_actors = int(getattr(collector.cfg.pipeline, 'num_actors', None) or 1)

    clients: list = []
    weights_info = None
    if local:
        from training.core.actor.weights_shm import WeightsSHM

        collector._weights_shm = WeightsSHM(max_state_dict_bytes=256 * 1024 * 1024)
        collector._weights_version = 1
        collector._weights_shm.write(WEIGHTS_TAG, _cpu_net_state_dict(collector.network), version=1)
        weights_info = collector._weights_shm.serialize_for_worker([WEIGHTS_TAG])
    else:
        from training.core.inference.client import InferenceClient
        from training.core.inference.server import InferenceServer

        server = InferenceServer(
            agent_config=collector._agent_config(),
            n_workers=n_actors,
            server_cfg=getattr(collector.cfg, 'inference', None),
            network_factory_path='training.paradigms.az.network.Agent',
            inference_handlers_module_path='training.paradigms.az._inference_handlers',
        )
        server.start()
        server.push_weights(_cpu_net_state_dict(collector.network))
        collector._inference_server = server
        collector._inference_clients = [
            InferenceClient(worker_id=index, pipe=server.get_worker_pipe(index)) for index in range(n_actors)
        ]
        clients = collector._inference_clients

    package = 'training.paradigms.az.mp_factories'
    base = {
        'build_env_factory_path': f'{package}.build_az_env_factory',
        'build_opp_registry_path': f'{package}.build_az_opp_registry',
        'build_policy_path': f'{package}.build_az_policy',
        'build_provider_path': f'{package}.build_az_provider',
        'spec_sampler_path': f'{package}.az_spec_sampler',
        'episode_runner_factory_path': f'{package}.build_az_selfplay_runner',
        'transition_queue': collector.ring,
        'push_episode_record': True,
    }

    if collector._opponent_pool is not None:
        from training.core.actor.weights_shm import WeightsSHM

        collector._opp_ring_shm = WeightsSHM()
        collector._opp_ring_shm.write(RING_TAG, {'snapshots': []}, version=0)
        ring_info = collector._opp_ring_shm.serialize_for_worker([RING_TAG])
        collector.runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda index: dict(
                base,
                provider_kwargs={
                    **({'weights_shm': weights_info} if local else {'inference_client': clients[index]}),
                    'opp_ring_shm': ring_info,
                },
            ),
        )
    elif local:
        collector.runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda index: dict(
                base,
                provider_kwargs={'weights_shm': weights_info},
            ),
        )
    else:
        collector.runtime.start_actors(
            n_actors=n_actors,
            actor_kwargs_factory=lambda index: dict(base, inference_client=clients[index]),
        )
    collector._spawned = True
