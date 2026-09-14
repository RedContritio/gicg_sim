"""Layout randomization must preserve raw trajectories and refresh all static input."""

import random

import numpy as np
import torch

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import episode_seeds
from training.paradigms.dmc.paradigm import DMCParadigm


def test_layout_changes_without_changing_gameplay():
    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    factory = make_env_factory(cfg, None, 41)
    envs = [factory(0, layout_seed=seed) for seed in (42, 104000, 105000)]
    try:
        assert all(not np.array_equal(envs[0].static_obs, env.static_obs) for env in envs[1:])
        for seed in (117, 281):
            for env in envs:
                env.reset(seed=seed, deck_seeds=(seed + 11, seed + 23))
                np.testing.assert_array_equal(env.static_obs, env._engine.get_static_obs())
            rng = random.Random(seed)
            for _ in range(512):
                base = envs[0]
                for env in envs[1:]:
                    assert env._engine.export_view() == base._engine.export_view()
                    np.testing.assert_array_equal(env.get_legal_actions(), base.get_legal_actions())
                    np.testing.assert_array_equal(env.get_legal_action_payments(), base.get_legal_action_payments())
                if base.done:
                    break
                action = rng.randrange(len(base.get_action_refs()))
                for env in envs:
                    env.step(action)
            assert all(env.done for env in envs)
    finally:
        for env in envs:
            env.close()


def test_collector_uses_fresh_layout_and_agent_static_cache_each_episode():
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    paradigm = DMCParadigm()
    net = paradigm.make_network(cfg)
    collector = paradigm.make_collector(
        cfg, make_env_factory(cfg, None, cfg.meta.seed), net, paradigm.make_opponent_pool(cfg, net)
    )
    try:
        statics = []
        for index in (1, 2):
            out = collector.collect(1, None)
            assert out.episode_stats[0]['seeds'] == episode_seeds(cfg.meta.seed, index)
            statics.append(collector.env.static_obs.copy())
            transitions, _ = out.runtime_metrics['dmc_episodes'][0]
            assert transitions
            # Compare provider inputs after game_start with a newly initialized cache.
            obs = collector.agent.build_obs_dict(collector.env)
            collector.agent.game_start(collector.env.static_obs)
            expected = collector.agent.build_obs_dict(collector.env)
            for key in obs:
                if isinstance(obs[key], torch.Tensor):
                    torch.testing.assert_close(obs[key], expected[key], rtol=0, atol=0)
        assert not np.array_equal(*statics)
    finally:
        collector.close()


def test_evaluation_pairs_share_layout_but_scenarios_do_not():
    from tools.experiments.evaluate_clean import evaluate

    torch.set_num_threads(1)
    one = evaluate('configs/dmc/pre_rl_small.toml', 'random', 2, 107000)
    two = evaluate('configs/dmc/pre_rl_small.toml', 'random', 2, 107000)
    assert one == two
    assert one['random']['layout_seeds'] == one['F1-D2']['layout_seeds']
    assert len(set(one['random']['layout_seeds'])) == 2
    assert one['random']['games'] == 4
