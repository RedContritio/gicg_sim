import random

import torch

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import update
from tools.experiments.semantic_training.rule_auxiliary import attach, loss
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_auxiliary_labels_preserve_rollout_and_train_shared_encoder(tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(94600)
    config = 'configs/dmc/native_starter.toml'
    cfg = load_cfg(config)
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    path = tmp_path / 'initial.pt'
    save_checkpoint({'format': FORMAT, 'shape': vars(shape), 'net': agent.net.state_dict()}, path)
    collections = []
    for stride in (0, 4):
        directory = tmp_path / str(stride)
        directory.mkdir()
        ev.initialize(config, path, 1)
        record = episode((1, 0, str(directory), 94600, 'configs/rule_validation/native_variants.toml', stride))
        collections.append(torch.load(record['path'], weights_only=False))
    plain, rows = collections
    assert len(plain) == len(rows)
    assert [(r['action'], r['old_logp'], r['reward']) for r in plain] == [
        (r['action'], r['old_logp'], r['reward']) for r in rows
    ]
    picked = [r for r in rows if 'rule_outcomes' in r][:4]
    assert picked
    attach(agent)
    batch = batch_observations([r['obs'] for r in picked], shape, 'cpu')
    logits, state, actions = agent.net(batch, return_actions=True)
    torch.testing.assert_close(logits, agent.net(batch))
    auxiliary = loss(agent.rule_head, state, actions, picked)
    auxiliary.backward()
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in agent.net.hook_encoder.parameters())
    assert all(p.grad is None for p in agent.net.base.heads['q'].parameters())
    anchor = SemanticAgent(shape)
    anchor.net.load_state_dict(agent.net.state_dict())
    anchor.net.requires_grad_(False)
    opt = torch.optim.AdamW([p for p in agent.net.parameters() if p.requires_grad], lr=1e-5)
    rule_opt = torch.optim.AdamW(agent.rule_head.parameters(), lr=0.0003)
    metrics = update(
        agent, anchor, opt, rows, [0.0, 0.0], random.Random(94600), epochs=1, rule_optimizer=rule_opt, rule_beta=0.5
    )
    assert metrics['updates'] > 0 and metrics['rule_loss'] >= 0
    assert rule_opt.state
