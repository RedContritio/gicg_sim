import json

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.audit_fit import audit
from tools.experiments.semantic_training.data import teacher_episode
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_audit_fit_reports_sane_metrics_on_teacher_episodes(tmp_path, monkeypatch):
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    checkpoint = tmp_path / 'policy.pt'
    save_checkpoint(
        {'format': 'semantic-q/2.0.0', 'shape': vars(agent.cfg), 'net': agent.net.state_dict()},
        checkpoint,
    )

    def end_when_possible(self, env):
        labels = env.get_action_labels()
        return next((i for i, label in enumerate(labels) if label[0] == 'EndTurn'), 0)

    monkeypatch.setattr(SemanticAgent, 'select_action', end_when_possible)
    teacher_dir = tmp_path / 'teacher'
    teacher_dir.mkdir()
    for index in range(2):
        teacher_episode(
            (
                'configs/dmc/native_starter.toml',
                index,
                str(teacher_dir),
                94120,
                'configs/rule_validation/native_variants.toml',
                str(checkpoint),
            )
        )
    output = tmp_path / 'fit.json'
    audit(
        'configs/dmc/native_starter.toml',
        str(checkpoint),
        str(teacher_dir),
        str(output),
        samples=16,
        device='cpu',
    )
    report = json.loads(output.read_text())
    metrics = report['metrics']
    assert 1 <= report['sample'] <= 16
    assert 0.0 <= metrics['agreement'] <= 1.0
    assert 0.0 <= metrics['tied_mass'] <= 1.0
    assert metrics['n_legal'] >= metrics['n_tied'] >= 1
    assert metrics['chance'] > 0
    assert metrics['uniform_ce'] > 0 and metrics['entropy'] > 0
    assert report['agreement_by_position_bucket']
