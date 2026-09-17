import hashlib

import pytest
import torch

from tools.experiments.semantic_training import paired_replay
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_replay import prepare_initial, validate_resume
from tools.experiments.semantic_training.paired_rl import _resume_paths
from tools.experiments.semantic_training.rule_auxiliary import attach, attach_adapter
from training.core.network import AgentConfig


def payload():
    return {
        'anchor_sha256': 'anchor',
        'paired_replay': {
            'beta': 0.5,
            'sha256': 'pairs',
            'batch_pairs': 8,
            'difference_beta': 1.0,
            'rng': ('state',),
            'calls': 7,
        },
    }


def test_validate_resume_returns_protocol():
    value = payload()
    assert validate_resume(value, anchor_sha256='anchor', pair_sha256='pairs') is value['paired_replay']


def test_validate_resume_accepts_control_beta():
    value = payload()
    value['paired_replay']['beta'] = 0.0
    assert (
        validate_resume(value, anchor_sha256='anchor', pair_sha256='pairs', expected_beta=0.0) is value['paired_replay']
    )


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('anchor_sha256', 'other', 'anchor mismatch'),
        ('paired_replay', None, 'wrong paired-replay protocol'),
    ],
)
def test_validate_resume_rejects_mismatch(field, value, message):
    candidate = payload()
    candidate[field] = value
    with pytest.raises(ValueError, match=message):
        validate_resume(candidate, anchor_sha256='anchor', pair_sha256='pairs')


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('beta', 0.0),
        ('sha256', 'other'),
        ('batch_pairs', 4),
        ('difference_beta', 0.5),
    ],
)
def test_validate_resume_rejects_protocol_mismatch(field, value):
    candidate = payload()
    candidate['paired_replay'][field] = value
    with pytest.raises(ValueError):
        validate_resume(candidate, anchor_sha256='anchor', pair_sha256='pairs')


def test_prepare_initial_reuses_resume_anchor(tmp_path, monkeypatch):
    shape = AgentConfig(
        n_counter_slots=2,
        n_hooks=2,
        max_ops_per_hook=2,
        max_actions=3,
        d_model=8,
        n_cross_layers=1,
    )
    agent = SemanticAgent(shape)
    attach(agent)
    attach_adapter(agent)
    diagnostic = {
        'format': 'paired-consequence/1.0.0',
        'parent_format': 'semantic-q/2.0.0',
        'shape': vars(shape),
        'net': agent.net.state_dict(),
        'rule_head': agent.rule_head.state_dict(),
        'rule_adapter': agent.rule_adapter.state_dict(),
    }
    source = tmp_path / 'source.pt'
    torch.save(diagnostic, source)
    destination = tmp_path / 'initial.pt'
    resume_initial = tmp_path / 'resume_initial.pt'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    torch.save(
        {
            'format': 'semantic-q/2.0.0',
            'shape': diagnostic['shape'],
            'net': diagnostic['net'],
            'rule_head': diagnostic['rule_head'],
            'rule_adapter': diagnostic['rule_adapter'],
            'diagnostic_sha256': digest,
        },
        resume_initial,
    )
    monkeypatch.setattr(paired_replay, 'load_checkpoint', lambda path, **kwargs: torch.load(path, **kwargs))
    monkeypatch.setattr(paired_replay, 'export_initial', lambda *args: pytest.fail('unexpected export'))
    payload = prepare_initial(source, destination, resume_initial=resume_initial)
    assert destination.read_bytes() == resume_initial.read_bytes()
    assert payload['diagnostic_sha256'] == digest


def test_prepare_initial_rejects_malformed_resume_anchor(tmp_path, monkeypatch):
    shape = AgentConfig(
        n_counter_slots=2,
        n_hooks=2,
        max_ops_per_hook=2,
        max_actions=3,
        d_model=8,
        n_cross_layers=1,
    )
    agent = SemanticAgent(shape)
    attach(agent)
    source = tmp_path / 'source.pt'
    torch.save(
        {
            'format': 'paired-consequence/1.0.0',
            'parent_format': 'semantic-q/2.0.0',
            'shape': vars(shape),
            'net': agent.net.state_dict(),
            'rule_head': agent.rule_head.state_dict(),
        },
        source,
    )
    resume_initial = tmp_path / 'resume_initial.pt'
    torch.save(
        {
            'format': 'semantic-q/2.0.0',
            'shape': vars(shape),
            'net': agent.net.state_dict(),
            'rule_head': {},
            'diagnostic_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        resume_initial,
    )
    monkeypatch.setattr(paired_replay, 'load_checkpoint', lambda path, **kwargs: torch.load(path, **kwargs))
    destination = tmp_path / 'initial.pt'
    with pytest.raises(RuntimeError):
        prepare_initial(source, destination, resume_initial=resume_initial)
    assert not destination.exists()


def test_resume_paths_loads_both_arm_checkpoints(tmp_path):
    for arm in ('auxiliary', 'control'):
        path = tmp_path / arm / 'ckpts/latest.pt'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'checkpoint')
    paths = _resume_paths(str(tmp_path))
    assert paths == {
        'auxiliary': tmp_path / 'auxiliary/ckpts/latest.pt',
        'control': tmp_path / 'control/ckpts/latest.pt',
    }


def test_resume_paths_accepts_template(tmp_path):
    for arm in ('auxiliary', 'control'):
        (tmp_path / f'{arm}.pt').write_bytes(b'checkpoint')
    paths = _resume_paths(str(tmp_path / '{arm}.pt'))
    assert paths == {'auxiliary': tmp_path / 'auxiliary.pt', 'control': tmp_path / 'control.pt'}


def test_resume_paths_rejects_a_single_checkpoint(tmp_path):
    checkpoint = tmp_path / 'latest.pt'
    checkpoint.write_bytes(b'checkpoint')
    with pytest.raises(ValueError, match='run directory'):
        _resume_paths(str(checkpoint))
