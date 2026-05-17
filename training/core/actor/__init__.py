"""training.core.actor — actor + inference + EpisodeRunner原子.

Owns:
- EpisodeRunner (actor + eval shared driver)
- NetworkProvider (Local + Remote) + factory
- Weights SHM + watcher
- Inference server / client
- Actor process / runtime topology
- IPC primitives (ring + queue)
"""

from training.core.actor.episode_runner import EpisodeRunner
from training.core.actor.network_provider import (
    LocalNetworkProvider,
    RemoteNetworkProvider,
)
from training.core.actor.policy import EpisodePolicyBase
from training.core.actor.provider_factory import build_network_provider

__all__ = [
    'EpisodeRunner',
    'EpisodePolicyBase',
    'LocalNetworkProvider',
    'RemoteNetworkProvider',
    'build_network_provider',
]
