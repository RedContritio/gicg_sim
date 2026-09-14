import numpy as np
import torch

from gicg_env import GicgEnv, PHASE_SELECT_ACTIVE
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_native_summon_choices_reach_semantic_q_and_training_batch():
    torch.set_num_threads(1)
    torch.manual_seed(42)
    team = ['菲谢尔', '芭芭拉', '砂糖']
    env = GicgEnv(
        team, team, pool='native_latest', seed=42, decks=[['送你一程', '送你一程'], ['甜甜花酿鸡', '甜甜花酿鸡']]
    )

    def play(kind, name=None):
        for i, (candidate, label, _) in enumerate(env.get_action_labels()):
            if candidate == kind and (name is None or label == name):
                env.step(i)
                return
        raise AssertionError(f'unavailable: {kind} {name}')

    try:
        env.reset(seed=42)
        while env.phase == PHASE_SELECT_ACTIVE:
            env.step(0)
        assert env.acting_player == 0
        play('EndTurn')
        env.set_player_dice(1, [0, 0, 0, 0, 0, 0, 0, 16])
        play('Skill', '夜巡影翼')
        play('Switch', '芭芭拉')
        play('Skill', '演唱，开始♪')
        play('EndTurn')
        env.get_legal_actions()
        assert env.acting_player == 0
        env.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 16])
        refs = env.get_action_refs()
        ids = env.get_action_identities()
        choices = np.flatnonzero(refs[:, 2] <= -2)
        assert len(choices) == 4  # two hand copies times two target instances
        assert len(set(ids[choices, 2])) == 2
        assert np.all(ids[choices, 3] == 1) and np.all(ids[choices, 4] == -1)
        cfg = load_cfg('configs/dmc/pre_rl_small.toml')
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape)
        agent.game_start(env.static_obs)
        scores = agent.logits(env)
        assert torch.isfinite(scores[choices]).all()
        batch = batch_observations([agent.observation(env)], shape, 'cpu')
        q = agent.net(batch)
        q[0, choices].square().mean().backward()
        assert agent.net.base.buff_encoder.state.weight.grad.abs().sum() > 0
        before = env.export_view()
        branch = env.clone()
        try:
            branch.step(int(choices[0]))
            assert env.export_view() == before
            assert len(branch.hand_refs(0)) == len(env.hand_refs(0)) - 1
        finally:
            branch.close()
    finally:
        env.close()
