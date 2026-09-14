from collections import Counter

import pytest
import torch

from tools.experiments.semantic_training.teams import eval_cases, matchup_key, sample_config
from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.rl_rollout import episode
from training.core.config.loader import load_cfg
from training.core.artifact_io import save_checkpoint
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.player_loader import FORMAT


def test_balanced_duo_cases_and_independent_training_sampling():
    cfg = load_cfg('configs/dmc/semantic_duo.toml')
    cases = eval_cases(cfg, 141000, 60)
    assert set(Counter(matchup_key(c.team_0, c.team_1) for c in cases).values()) == {4}
    assert len({matchup_key(c.team_0, c.team_1) for c in cases}) == 15
    assert cases == eval_cases(cfg, 141000, 60)
    assert cases != eval_cases(cfg, 141001, 60)
    with pytest.raises(ValueError):
        eval_cases(cfg, 141000, 64)
    samples = [sample_config(cfg, i) for i in range(100)]
    assert all(len(set(c.scenario.team_0 + c.scenario.team_1)) == 4 for c in samples)
    assert set(x for c in samples for x in c.scenario.team_0 + c.scenario.team_1) == set(cfg.scenario.char_pool)
    assert cfg.scenario.team_0 == ['赤蝶', '墨客']


def test_duo_checkpoint_inference_and_terminal_rollout(tmp_path):
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/semantic_duo.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    path = tmp_path / 'initial.pt'
    save_checkpoint({'format': FORMAT, 'shape': vars(shape), 'net': agent.net.state_dict()}, path)
    ev.initialize('configs/dmc/semantic_duo.toml', path)
    result = episode((1, 0, str(tmp_path), 140000))
    rows = torch.load(result['path'], weights_only=False)
    assert len(rows) > 0 and result['reward'] in (-1, 0, 1)
    assert rows[0]['obs']['char_skill_refs'].shape[0] > 0
