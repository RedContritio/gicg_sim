"""Initial weights and the actually consumed exploration stream follow the run seed."""

from types import SimpleNamespace

import torch

from training.core.config.loader import load_cfg
from training.paradigms.dmc.paradigm import DMCParadigm
from training.paradigms.dmc.collector import DMCSerialCollector


def test_seeded_network_is_cached_and_reproducible():
    cfg = load_cfg('configs/dmc/readiness_base.toml')
    torch.set_num_threads(1)
    one = DMCParadigm()
    network = one.make_network(cfg)
    assert one.make_network(cfg) is network
    two = DMCParadigm().make_network(cfg)
    for key, tensor in network.state_dict().items():
        torch.testing.assert_close(tensor, two.state_dict()[key], rtol=0, atol=0)
    assert network._agent.rng.random() == two._agent.rng.random()


def test_saved_collector_rng_is_the_agent_exploration_rng():
    cfg = load_cfg('configs/dmc/readiness_base.toml')
    agent = SimpleNamespace()
    collector = DMCSerialCollector(cfg, None, agent, None, None)
    assert agent.rng is collector._rng_action
    snapshot = collector.state_dict()
    expected = [agent.rng.random() for _ in range(10)]
    collector.load_state_dict(snapshot)
    assert [agent.rng.random() for _ in range(10)] == expected
