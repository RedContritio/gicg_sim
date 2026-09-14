"""Oracle labels, masking and data isolation for the stage 3 experiments."""

import copy

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from tools.experiments.readiness_cost import GROUPS
from tools.experiments.tactical_data import label_actions, step_checked, utility
from tools.experiments.tactical_learning import batch_rows, kind_means
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._episode import capture_obs
from training.paradigms.dmc.config import DMCParadigmConfig


def test_utility_perspective_and_true_draw():
    before = {'winner': -1, 'players': [{'chars': [{'hp': 5}]}, {'chars': [{'hp': 5}]}]}
    after = copy.deepcopy(before)
    after['players'][1]['chars'][0]['hp'] = 0
    after['winner'] = 0
    assert utility(before, after, 0) == 25
    assert utility(before, after, 1) == -25
    after['winner'] = 2
    assert utility(before, after, 0) == 5
    after['winner'] = 3
    with pytest.raises(ValueError):
        utility(before, after, 0)


def test_reserved_rules_absent_from_training_groups():
    reserved = {'以逸待劳', '速速茶点'}
    assert not reserved.intersection(card for cards in GROUPS.values() for card in cards)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    assert not reserved.intersection(cfg.scenario.card_pool)


def test_labels_are_real_and_do_not_mutate_parent():
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    agent = DmcAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    env = GicgEnv(
        ['赤蝶'],
        ['墨客'],
        card_pool=['测试卡_碎片'],
        pool=['v_legacy', 'test_basic'],
        data_dir='data',
        fix_dice=[0, 0, 0, 0, 0, 0, 0, 12],
    )
    try:
        env.reset(seed=100)
        env.get_legal_actions()
        before = env._engine.export_view()
        with pytest.raises(ValueError, match='illegal tactical'):
            step_checked(env, -1)
        obs_before = env._get_obs().copy()
        actions = env.get_action_labels()
        labels = label_actions(env)
        assert env._engine.export_view() == before
        np.testing.assert_array_equal(env._get_obs(), obs_before)
        fragment = [i for i, label in enumerate(actions) if label[1] == '测试卡_碎片' and label[0] == 'Card']
        assert fragment
        np.testing.assert_array_equal(labels[fragment], np.ones(len(fragment)))
        agent.game_start(env.static_obs)
        obs = capture_obs(env, agent)
        # Artificial ties here test the loss mask only; engine data remains intact.
        tied = np.zeros_like(labels)
        tied[0:2] = 1
        row = {'obs': obs, 'utility': tied}
        batch, target = batch_rows([row], agent.cfg.max_actions)
        assert target.sum() == 1
        assert target[0, 0] == target[0, 1] == 0.5
        assert target[0, obs['n_legal'] :].sum() == 0
        assert 'utility' not in batch
        assert kind_means([row])
    finally:
        env.close()
