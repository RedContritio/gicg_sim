"""v_phase2 池 — Python GicgEnv 加载 spike test。

验证:
- pool=['v_phase2'] 能加载 7 个角色
- card_pool=v_phase2 6 张代表卡能识别
- dynamic obs size 正常
"""

from __future__ import annotations

import pytest

from gicg_env import GicgEnv


V_PHASE2_CHARS = ['凯亚', '凝光', '坎蒂丝', '砂糖', '柯莱', '克洛琳德', '玛薇卡']
V_PHASE2_CARDS = ['旅行剑', '魔导绪论', '甜甜花酿鸡', '蒙德土豆饼', '派蒙', '鸣神大社']


@pytest.mark.parametrize('char_name', V_PHASE2_CHARS)
def test_v_phase2_char_loads(char_name):
    env = GicgEnv([char_name], [char_name], card_pool=[], pool=['v_phase2'], data_dir='data')
    assert env._dynamic_obs_size > 0


def test_v_phase2_pool_with_cards():
    env = GicgEnv(['凯亚'], ['凯亚'], card_pool=V_PHASE2_CARDS, pool=['v_phase2'], data_dir='data')
    assert env._dynamic_obs_size > 0


def test_v_phase2_two_char_match():
    env = GicgEnv(['凯亚'], ['克洛琳德'], card_pool=V_PHASE2_CARDS, pool=['v_phase2'], data_dir='data')
    assert env._dynamic_obs_size > 0
