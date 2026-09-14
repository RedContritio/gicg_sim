"""Matched-pair consequence experiment invariants."""

from types import SimpleNamespace
import hashlib
import random
import numpy as np
import pytest
import torch

from tools.experiments.semantic_training import paired_replay, rl_update
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_lessons import HELDOUT_VALUES, TRAIN_VALUES, build_pair, tasks
from tools.experiments.semantic_training.paired_training import objective
from tools.experiments.semantic_training.player_loader import FORMAT, load_semantic_payload
from tools.experiments.semantic_training.rule_auxiliary import attach
from training.core.artifact_io import KEY, load_checkpoint, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


CONFIG = 'configs/dmc/native_starter.toml'
CATALOG = 'configs/rule_validation/native_variants.toml'


def test_literal_and_state_splits_are_disjoint_and_reproducibly_paired():
    jobs = tasks(CONFIG, CATALOG, {}, seed=95000, contexts=2)
    train_values = {value for pair in TRAIN_VALUES for value in pair}
    heldout_values = {value for pair in HELDOUT_VALUES for value in pair}
    assert train_values.isdisjoint(heldout_values)

    observed = {
        split: {value for job in jobs if job['split'] == split for value in job['values']}
        for split in ('train', 'states', 'values')
    }
    assert observed == {'train': train_values, 'states': train_values, 'values': heldout_values}
    assert {job['seed'] for job in jobs if job['split'] == 'train'}.isdisjoint(
        {job['seed'] for job in jobs if job['split'] != 'train'}
    )

    contexts = {}
    for job in jobs:
        key = (job['split'], job['parameter']['id'], job['seed'], job['layout'], job['hp'])
        contexts.setdefault(key, set()).add(job['values'])
    expected_pairs = set(TRAIN_VALUES)
    assert all(
        values == (set(HELDOUT_VALUES) if key[0] == 'values' else expected_pairs) for key, values in contexts.items()
    )


def test_beta_zero_is_the_absolute_control_and_paired_term_changes_gradient():
    pred = torch.tensor([[[0.1], [0.4]]], requires_grad=True)
    truth = torch.tensor([[[0.2], [0.8]]])
    pairs = [{'field': 0}]

    control = objective(pred, truth, pairs, beta=0.0)
    paired = objective(pred, truth, pairs, beta=1.0)
    expected_difference = ((pred[:, 1, 0] - pred[:, 0, 0]) - (truth[:, 1, 0] - truth[:, 0, 0])).square().mean()
    torch.testing.assert_close(paired - control, expected_difference)

    control_grad = torch.autograd.grad(control, pred, retain_graph=True)[0]
    paired_grad = torch.autograd.grad(paired, pred)[0]
    assert torch.isfinite(control_grad).all() and torch.isfinite(paired_grad).all()
    assert not torch.equal(control_grad, paired_grad)


def test_real_engine_pair_changes_only_rule_ir_and_oracle_consequence():
    torch.set_num_threads(1)
    cfg = load_cfg(CONFIG)
    shape = vars(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    pair = build_pair(tasks(CONFIG, CATALOG, shape, seed=95000, contexts=1)[0])
    low, high = pair['rows']

    assert low['action'] == high['action']
    assert low['target'][pair['field']] != high['target'][pair['field']]
    for key in low['obs']:
        if key == 'hook_ir':
            assert not np.array_equal(low['obs'][key], high['obs'][key])
        else:
            assert np.array_equal(low['obs'][key], high['obs'][key]), key


def test_replay_samples_only_train_split_and_repeats_from_seed(monkeypatch):
    pairs = [
        {'split': split, 'parameter': parameter, 'token': token}
        for token, (split, parameter) in enumerate(
            [('train', 'a'), ('states', 'a'), ('values', 'b'), ('train', 'b'), ('train', 'a')]
        )
    ]
    sampled = []

    def fake_predict(_agent, selected):
        sampled.append(tuple(pair['token'] for pair in selected))
        return torch.zeros(len(selected), 2, 1), torch.zeros(len(selected), 2, 1)

    monkeypatch.setattr(paired_replay, 'predict', fake_predict)
    monkeypatch.setattr(paired_replay, 'objective', lambda pred, _truth, _pairs, beta: pred.sum() + beta)
    first = paired_replay.PairedReplay(pairs, seed=19, batch_pairs=12)
    second = paired_replay.PairedReplay(pairs, seed=19, batch_pairs=12)
    first(None)
    second(None)
    assert sampled[0] == sampled[1]
    assert set(sampled[0]) <= {0, 3, 4}
    assert set(first.strata) == {'a', 'b'}


class _ToyPolicy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(0.0))

    def forward(self, batch, return_actions=False):
        size = batch['legal_mask'].shape[0]
        logits = torch.stack((self.weight.expand(size), -self.weight.expand(size)), dim=1)
        if return_actions:
            state = self.weight.expand(size, 1)
            actions = self.weight.expand(size, 2, 1)
            return logits, state, actions
        return logits


def _toy_update(monkeypatch, *, with_auxiliary):
    monkeypatch.setattr(
        rl_update,
        'batch_observations',
        lambda observations, _cfg, _device: {
            'legal_mask': torch.ones(len(observations), 2, dtype=torch.bool),
        },
    )
    agent = SimpleNamespace(net=_ToyPolicy(), cfg=None, device='cpu')
    anchor = SimpleNamespace(net=_ToyPolicy())
    anchor.net.requires_grad_(False)
    optimizer = torch.optim.SGD(agent.net.parameters(), lr=0.1)
    rows = [dict(obs={}, action=0, old_logp=-np.log(2), reward=1, side=0)]
    calls = []
    rule_optimizer = None
    if with_auxiliary:
        agent.rule_head = torch.nn.Linear(1, 1, bias=False)
        rule_optimizer = torch.optim.SGD(agent.rule_head.parameters(), lr=0.1)

    def auxiliary(model):
        calls.append(True)
        return (model.net.weight + model.rule_head.weight.sum()).square()

    metrics = rl_update.update(
        agent,
        anchor,
        optimizer,
        rows,
        [0, 0],
        random.Random(7),
        epochs=1,
        rule_optimizer=rule_optimizer,
        rule_beta=0.5 if with_auxiliary else 0.0,
        auxiliary_loss=auxiliary,
    )
    return agent, metrics, calls


def test_optional_rl_auxiliary_is_control_gated_and_backpropagates(monkeypatch):
    _, control, control_calls = _toy_update(monkeypatch, with_auxiliary=False)
    agent, auxiliary, auxiliary_calls = _toy_update(monkeypatch, with_auxiliary=True)
    assert control['updates'] == auxiliary['updates'] == 1
    assert control_calls == []
    assert auxiliary_calls == [True]
    assert auxiliary['rule_loss'] >= 0
    assert agent.rule_head.weight.grad is not None and agent.rule_head.weight.grad.abs().sum() > 0


def test_diagnostic_export_is_strict_and_preserves_parent_provenance(tmp_path):
    cfg = load_cfg(CONFIG)
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    attach(agent)
    source = tmp_path / 'paired.pt'
    destination = tmp_path / 'initial.pt'
    save_checkpoint(
        {
            'format': 'paired-consequence/1.0.0',
            'parent_format': FORMAT,
            'shape': vars(shape),
            'net': agent.net.state_dict(),
            'rule_head': agent.rule_head.state_dict(),
        },
        source,
    )

    paired_replay.export_initial(source, destination)
    exported = load_semantic_payload(destination)
    assert exported['format'] == FORMAT
    assert exported['diagnostic_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert exported['diagnostic_sha256'] in load_checkpoint(destination, weights_only=False)[KEY]['parents']

    malformed = load_checkpoint(source, weights_only=False)
    malformed['net'] = dict(malformed['net'])
    malformed['net'].pop(next(iter(malformed['net'])))
    bad = tmp_path / 'bad.pt'
    save_checkpoint(malformed, bad)
    with pytest.raises(RuntimeError, match='Missing key'):
        paired_replay.export_initial(bad, tmp_path / 'should-not-exist.pt')
