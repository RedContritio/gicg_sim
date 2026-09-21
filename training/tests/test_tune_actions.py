"""Joint tune actions expose discarded rule and source die through the full Q head."""

import numpy as np
import torch

from gicg_env import ACTION_TUNE, GicgEnv
from training.tests._helpers import keep_all_rerolls
from tools.experiments.action_audit import check_action_aliases
from tools.experiments.tactical_learning import batch_rows
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._episode import capture_obs
from training.paradigms.dmc.config import DMCParadigmConfig


def test_tune_rule_color_and_logits():
    torch.set_num_threads(1)
    torch.manual_seed(41)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    agent = DmcAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    env = GicgEnv(
        ['赤蝶'], ['墨客'], card_pool=['美味烧鸡', '测试卡_碎片'], pool=['v_legacy', 'test_basic'], data_dir='data'
    )
    try:
        env.reset(seed=500)
        keep_all_rerolls(env)
        env.get_legal_actions()
        env.set_player_dice(env.acting_player, [0, 0, 2, 2, 0, 0, 0, 0])
        refs = env.get_action_refs()
        ids = np.flatnonzero(refs[:, 0] == ACTION_TUNE)
        assert len(ids) == 4
        assert len(set(refs[ids, 1])) == 2
        assert set(refs[ids, 2]) == {2, 3}
        np.testing.assert_array_equal(refs[ids, 2], env.get_action_identities()[ids, 2])
        check_action_aliases(env)
        agent.game_start(env.static_obs)
        obs = capture_obs(env, agent)
        batch, _ = batch_rows([{'obs': obs, 'utility': np.zeros(obs['n_legal'])}], agent.cfg.max_actions)
        agent.net.eval()
        logits, _, _ = agent.forward_batch(batch)
        assert len(set(logits[0, ids].detach().tolist())) == 4
        logits[0, ids].sum().backward()
        assert agent.net.tune_source_emb.weight.grad.abs().sum() > 0
        assert agent.net.tune_action_emb.grad.abs().sum() > 0
    finally:
        env.close()
