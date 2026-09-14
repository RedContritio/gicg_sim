import numpy as np
import torch

from gicg_env import ACTION_REROLL, GicgEnv, PHASE_SELECT_ACTIVE
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from training.core.matchup.greedy_player import GreedyPlayer


def test_native_reroll_choices_have_distinct_embeddings_and_gradients():
    torch.set_num_threads(1)
    torch.manual_seed(42)
    team = ['凯亚', '迪卢克', '芭芭拉']
    env = GicgEnv(team, team, pool='native_latest', seed=42, decks=[['一掷乾坤'], ['甜甜花酿鸡']])
    try:
        env.reset(seed=42)
        while env.phase == PHASE_SELECT_ACTIVE:
            env.step(0)
        env.set_player_dice(0, [2, 0, 0, 0, 0, 0, 0, 1])
        card = next(
            i for i, (kind, name, _) in enumerate(env.get_action_labels()) if kind == 'Card' and name == '一掷乾坤'
        )
        env.step(card)
        refs, ids = env.get_action_refs(), env.get_action_identities()
        np.testing.assert_array_equal(refs, [[ACTION_REROLL, 0, 0], [ACTION_REROLL, 1, 0], [ACTION_REROLL, 2, 0]])
        np.testing.assert_array_equal(ids[:, 1:3], refs[:, 1:3])
        assert np.all(env.get_legal_action_payments() == 0)
        cfg = load_cfg('configs/dmc/pre_rl_small.toml')
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape)
        agent.game_start(env.static_obs)
        batch = batch_observations([agent.observation(env)], shape, 'cpu')
        q = agent.net(batch)
        assert torch.isfinite(q[0, :3]).all()
        assert len(set(q[0, :3].detach().tolist())) == 3
        q[0, :3].square().mean().backward()
        assert agent.net.base.reroll_count_proj.weight.grad.abs().sum() > 0
        assert agent.net.base.reroll_color_emb.weight.grad.abs().sum() > 0
        assert agent.net.base.buff_encoder.state.weight.grad.abs().sum() > 0
        # Confirm is its own semantic choice, and subsequent rounds still work.
        before = env.get_action_refs().copy()
        # D1/D2 complete rerolls with the same fixed dice-value baseline.
        for depth in (1, 2):
            greedy = GreedyPlayer('F1', depth, seed=42)
            branch = env.clone()
            try:
                for _ in range(18):
                    if branch.get_legal_actions()[0][0] != ACTION_REROLL:
                        break
                    old = branch.get_action_refs().copy()
                    choice, info = greedy.select_with_info(branch)
                    assert info['scored'][0][0] == choice
                    np.testing.assert_array_equal(branch.get_action_refs(), old)
                    branch.step(choice)
                assert branch.get_legal_actions()[0][0] != ACTION_REROLL
            finally:
                branch.close()
        branch = env.clone()
        try:
            branch.step(2)
            branch.step(0)
            np.testing.assert_array_equal(branch.get_action_refs(), [[ACTION_REROLL, 0, 8]])
            assert torch.isfinite(agent.logits(branch)[0])
            branch.step(0)
            for _ in range(10):
                kinds, _ = branch.get_legal_actions()
                if kinds[0] != ACTION_REROLL:
                    break
                branch.step(0)
            assert branch.get_legal_actions()[0][0] != ACTION_REROLL
            np.testing.assert_array_equal(env.get_action_refs(), before)
        finally:
            branch.close()
    finally:
        env.close()
