"""Real counterfactual pairing and explicit frozen-readout behavior."""

import pytest
import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.transfer_probe import collect, load_agent
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def setup():
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    attach(agent)
    return cfg, agent


def test_real_probe_pairs_preserve_state_and_reverse_damage_leader():
    cfg, agent = setup()
    result = collect(agent, cfg, seeds=(94510,), layouts=(7,))
    rows = result['cases']
    assert len(rows) == 4
    assert [r['expected'] for r in rows] == [1, 0, 1, 0]
    assert [list(r['observed']) for r in rows] == [[2, 6], [6, 2], [4, 8], [8, 4]]
    assert len({r['data_sha256'] for r in rows}) == 4
    assert all(len(r['predicted']) == len(r['scores']) == 2 for r in rows)


def test_missing_readout_requires_explicit_compatible_source(tmp_path):
    _, agent = setup()
    policy, source = tmp_path / 'policy.pt', tmp_path / 'readout.pt'
    payload = dict(format=FORMAT, shape=vars(agent.cfg), net=agent.net.state_dict())
    save_checkpoint(payload, policy)
    save_checkpoint(dict(payload, rule_head=agent.rule_head.state_dict()), source)
    with pytest.raises(ValueError, match='explicit frozen readout'):
        load_agent(policy)
    restored, meta = load_agent(policy, source)
    assert meta['readout_external']
    assert meta['checkpoint_sha256'] != meta['readout_checkpoint_sha256']
    for key, expected in agent.rule_head.state_dict().items():
        torch.testing.assert_close(restored.rule_head.state_dict()[key], expected)


def test_residual_policy_probe_uses_embedded_readout(tmp_path):
    from tools.experiments.semantic_training.consequence_policy import ConsequencePolicyNet, FORMAT as RESIDUAL_FORMAT

    cfg, agent = setup()
    model = ConsequencePolicyNet(agent.net, agent.rule_head, agent.cfg.d_model)
    path = tmp_path / 'residual.pt'
    save_checkpoint(
        dict(format=RESIDUAL_FORMAT, shape=vars(agent.cfg), net=model.state_dict(), use_consequences=True), path
    )
    restored, meta = load_agent(path)
    assert restored.rule_head is restored.net.rule_head
    assert meta['use_consequences'] and not meta['readout_external']
    result = collect(restored, cfg, seeds=(94510,), layouts=(7,))
    assert len(result['cases']) == 4
    with pytest.raises(ValueError, match='external replacement'):
        load_agent(path, path)
