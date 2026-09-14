import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.data import teacher_episode
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_dagger_executes_learner_but_retains_expert_labels(tmp_path, monkeypatch):
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    checkpoint = tmp_path / 'learner.pt'
    save_checkpoint({'net': agent.net.state_dict()}, checkpoint)

    def end_when_possible(self, env):
        labels = env.get_action_labels()
        return next((i for i, label in enumerate(labels) if label[0] == 'EndTurn'), 0)

    monkeypatch.setattr(SemanticAgent, 'select_action', end_when_possible)
    result = teacher_episode(
        (
            'configs/dmc/native_starter.toml',
            1,
            str(tmp_path),
            94120,
            'configs/rule_validation/native_variants.toml',
            str(checkpoint),
        )
    )
    rows = torch.load(result['path'], weights_only=False)['rows']
    assert result['rule_variant']['variant'] and result['learner_decisions'] > 0
    assert result['expert_disagreements'] > 0
    assert any(r['executed_action'] not in r['tied'] for r in rows)
    assert all(r['tied'] for r in rows)
