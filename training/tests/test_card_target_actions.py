"""Different legal card targets must remain distinguishable through the Q head."""

import numpy as np
import torch

from gicg_env import GicgEnv
from tools.experiments.tactical_data import label_actions, step_checked
from tools.experiments.tactical_learning import batch_rows
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._episode import capture_obs
from training.paradigms.dmc.config import DMCParadigmConfig


def test_joint_card_targets_reach_logits_and_gradients():
    torch.set_num_threads(1)
    torch.manual_seed(41)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    agent = DmcAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    env = GicgEnv(
        ['赤蝶', '墨客'],
        ['赤蝶', '墨客'],
        card_pool=['美味烧鸡'],
        pool=['v_legacy', 'test_basic'],
        data_dir='data',
        fix_dice=[0, 0, 0, 0, 0, 0, 0, 12],
    )
    try:
        env.reset(seed=300)
        for _ in range(2):
            index = next(i for i, a in enumerate(env.get_action_labels()) if a[:2] == ('Skill', '枪'))
            step_checked(env, index)
        refs = env.get_action_refs()
        identities = env.get_action_identities()
        cards = np.flatnonzero(refs[:, 0] == 1)
        assert len(cards) == 2
        assert set(refs[cards, 2]) == {0, 1}
        np.testing.assert_array_equal(refs[cards, 2], identities[cards, 4])
        np.testing.assert_array_equal(
            env.get_legal_action_payments()[cards[0]], env.get_legal_action_payments()[cards[1]]
        )
        values = label_actions(env)
        assert set(values[cards]) == {0, 1}
        agent.game_start(env.static_obs)
        batch, _ = batch_rows([{'obs': capture_obs(env, agent), 'utility': values}], agent.cfg.max_actions)
        agent.net.eval()
        logits, _, _ = agent.forward_batch(batch)
        difference = logits[0, cards[0]] - logits[0, cards[1]]
        assert abs(float(difference.detach())) > 1e-7
        difference.backward()
        assert agent.net.card_target_emb.weight.grad.abs().sum() > 0
        # Simulates the old lost-target wire: the two actions become identical.
        batch['action_refs'][0, cards, 2] = -1
        with torch.no_grad():
            collapsed, _, _ = agent.forward_batch(batch)
        torch.testing.assert_close(collapsed[0, cards[0]], collapsed[0, cards[1]], rtol=0, atol=0)
    finally:
        env.close()
