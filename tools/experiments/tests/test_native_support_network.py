import numpy as np
import torch

from gicg_env import GicgEnv, PHASE_SELECT_ACTIVE, OBS_BUFF_ROWS
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_support_replacement_reaches_native_semantic_network():
    torch.set_num_threads(1)
    torch.manual_seed(43)
    team = ['凯亚', '砂糖', '芭芭拉']
    cards = ['派蒙', '鸣神大社', '派蒙', '鸣神大社']
    env = GicgEnv(team, team, pool='native_latest', seed=42, decks=[cards, cards])
    try:
        env.reset(seed=42)
        while env.phase == PHASE_SELECT_ACTIVE:
            env.step(0)
        for name in cards:
            env.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 16])
            index = next(
                i for i, (kind, label, _) in enumerate(env.get_action_labels()) if kind == 'Card' and label == name
            )
            env.step(index)
        ref = next(ref for ref, name in env._engine.get_card_names().items() if name == '派蒙')
        env.set_player_hand(0, [ref])
        env.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 16])
        refs, identities = env.get_action_refs(), env.get_action_identities()
        choices = np.flatnonzero(refs[:, 2] <= -2 - OBS_BUFF_ROWS)
        assert len(choices) == 4
        np.testing.assert_array_equal(identities[choices, 2], OBS_BUFF_ROWS + np.arange(4))
        assert np.all(identities[choices, 3] == 0)
        cfg = load_cfg('configs/dmc/pre_rl_small.toml')
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape)
        agent.game_start(env.static_obs)
        assert torch.isfinite(agent.logits(env)[choices]).all()
        batch = batch_observations([agent.observation(env)], shape, 'cpu')
        agent.net(batch)[0, choices].square().mean().backward()
        assert agent.net.base.buff_encoder.state.weight.grad.abs().sum() > 0
        before = env.export_view()
        branch = env.clone()
        try:
            branch.step(int(choices[-1]))
            assert env.export_view() == before
            assert len(branch.hand_refs(0)) == 0
            assert int(branch.dice_counts(0).sum()) == 13
        finally:
            branch.close()
    finally:
        env.close()
