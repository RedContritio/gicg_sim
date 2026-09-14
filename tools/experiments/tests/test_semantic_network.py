import pytest
import numpy as np
import torch

from tools.experiments.decision_audit.run import d1
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


@pytest.mark.parametrize('config', ['configs/dmc/pre_rl_small.toml', 'configs/dmc/semantic_duo.toml'])
def test_semantic_network_real_trajectory_layout_and_batch_parity(config):
    torch.set_num_threads(1)
    torch.manual_seed(122000)
    cfg = load_cfg(config)
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agents = [SemanticAgent(shape) for _ in range(2)]
    agents[1].net.load_state_dict(agents[0].net.state_dict())
    factory = make_env_factory(cfg, None, 122000)
    envs = [factory(0, layout_seed=seed) for seed in (7, 19)]
    player = d1(11)
    observations = []
    try:
        for env, agent in zip(envs, agents):
            env.reset(seed=12, deck_seeds=(13, 14))
            agent.game_start(env.static_obs)
        for step in range(512):
            a, b = envs
            assert a.export_view() == b.export_view()
            if a.done:
                break
            np.testing.assert_array_equal(a.get_action_identities(), b.get_action_identities())
            qs = [agent.logits(env) for env, agent in zip(envs, agents)]
            torch.testing.assert_close(qs[0], qs[1], atol=1e-5, rtol=1e-5)
            if step in (0, 6):
                observations.extend(agent.observation(env) for env, agent in zip(envs, agents))
            action = player.select_action(a)
            for env in envs:
                env.step(action)
        assert a.done
        batch = batch_observations(observations, shape, 'cpu')
        q = agents[0].net(batch)
        loss = q[:, 0].square().mean()
        loss.backward()
        assert torch.isfinite(loss)
        assert agents[0].net.relation[0].weight.grad.abs().sum() > 0
        assert agents[0].net.card_count[0].weight.grad.abs().sum() > 0
    finally:
        for env in envs:
            env.close()
