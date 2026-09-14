import random

import numpy as np
import pytest
import torch

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import policy_loss, update
from training.core.artifact_io import save_checkpoint, load_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from tools.experiments.semantic_training.value_baseline import attach, advantages, StateValueHead


def test_terminal_policy_loss_reward_direction_mask_and_clip():
    logits = torch.tensor([[0.0, 0.0, 50.0], [0.0, 0.0, 50.0]], requires_grad=True)
    mask = torch.tensor([[True, True, False], [True, True, False]])
    actions = torch.tensor([0, 0])
    old = torch.tensor([-np.log(2), -np.log(2)], dtype=torch.float32)
    advantages = torch.tensor([1.0, -1.0])
    loss, metrics = policy_loss(logits, mask, actions, old, advantages, logits.detach(), beta=0)
    loss.backward()
    assert logits.grad[0, 0] < 0  # Increase winner action probability.
    assert logits.grad[1, 0] > 0  # Decrease loser action probability.
    assert torch.equal(logits.grad[:, 2], torch.zeros(2))
    assert metrics['sample_kl'].abs() < 1e-7
    assert metrics['anchor_kl'].abs() < 1e-7


@pytest.mark.parametrize('state_baseline', [False, True])
@pytest.mark.parametrize('temperature', [1.0, 0.5])
def test_real_rl_rollout_probability_parity_and_update(tmp_path, state_baseline, temperature):
    torch.set_num_threads(1)
    torch.manual_seed(128001)
    cfg = load_cfg('configs/dmc/semantic_goal.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    actor = SemanticAgent(shape)
    path = tmp_path / 'initial.pt'
    payload = {'format': FORMAT, 'shape': vars(shape), 'net': actor.net.state_dict()}
    payload['settings'] = {'temperature': temperature}
    if state_baseline:
        attach(actor)
        with torch.no_grad():
            actor.value_head.layers[-1].weight.normal_(0, 0.01)
        payload['value_head'] = actor.value_head.state_dict()
    save_checkpoint(payload, path)
    ev.initialize('configs/dmc/semantic_goal.toml', path)
    record = episode((1, 0, str(tmp_path), 128000))
    rows = torch.load(record['path'], weights_only=False)
    assert rows and record['reward'] in (-1, 0, 1)
    assert all(row['reward'] == record['reward'] and row['side'] == 0 for row in rows)
    batch = batch_observations([r['obs'] for r in rows], shape, 'cpu')
    with torch.no_grad():
        logits, features = actor.net(batch, return_state=True)
        torch.testing.assert_close(logits, actor.net(batch))
        if state_baseline:
            torch.testing.assert_close(
                actor.value_head(features), torch.tensor([r['old_value'] for r in rows]), atol=1e-5, rtol=1e-5
            )
        logp = (logits / temperature).masked_fill(~batch['legal_mask'], -1e9).log_softmax(-1)
        expected = logp[torch.arange(len(rows)), torch.tensor([r['action'] for r in rows])]
    torch.testing.assert_close(expected, torch.tensor([r['old_logp'] for r in rows]), atol=1e-5, rtol=1e-5)
    anchor = SemanticAgent(shape)
    anchor.net.load_state_dict(actor.net.state_dict())
    anchor.net.requires_grad_(False)
    before = actor.net.numeric[0].weight.detach().clone()
    opt = torch.optim.AdamW([p for p in actor.net.parameters() if p.requires_grad], lr=1e-5)
    value_opt = torch.optim.AdamW(actor.value_head.parameters(), lr=0.0003) if state_baseline else None
    metrics = update(
        actor,
        anchor,
        opt,
        rows,
        [0.0, 0.0],
        random.Random(128002),
        epochs=1,
        value_optimizer=value_opt,
        temperature=temperature,
    )
    assert metrics['updates'] > 0 and not metrics['early_stop_kl']
    assert not torch.equal(actor.net.numeric[0].weight, before)
    assert all(p.grad is None for p in anchor.net.parameters())
    if state_baseline:
        assert metrics['value_loss'] >= 0
        assert value_opt.state


def test_value_baseline_gradient_isolation_and_frozen_advantages():
    head = StateValueHead(4)
    features = torch.randn(3, 4, requires_grad=True)
    value = head(features)
    torch.testing.assert_close(value, torch.zeros(3))
    (value - 1).square().mean().backward()
    assert features.grad is None
    assert head.layers[-1].bias.grad.abs().sum() > 0
    rewards = torch.tensor([1.0, -1.0], requires_grad=True)
    old = torch.tensor([0.2, -0.3], requires_grad=True)
    result = advantages(rewards, old)
    torch.testing.assert_close(result, torch.tensor([0.8, -0.7]))
    assert not result.requires_grad


def test_value_head_optimizer_checkpoint_resume(tmp_path):
    torch.manual_seed(17)
    head = StateValueHead(4)
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.0003)
    features, target = torch.randn(8, 4), torch.linspace(-1, 1, 8)

    def step(model, opt):
        opt.zero_grad()
        (model(features) - target).square().mean().backward()
        opt.step()

    step(head, optimizer)
    path = tmp_path / 'critic.pt'
    save_checkpoint({'value_head': head.state_dict(), 'value_optimizer': optimizer.state_dict()}, path)
    payload = load_checkpoint(path, map_location='cpu', weights_only=False)
    restored = StateValueHead(4)
    restored.load_state_dict(payload['value_head'])
    restored_opt = torch.optim.AdamW(restored.parameters(), lr=0.0003)
    restored_opt.load_state_dict(payload['value_optimizer'])
    step(head, optimizer)
    step(restored, restored_opt)
    for a, b in zip(head.parameters(), restored.parameters()):
        torch.testing.assert_close(a, b, rtol=0, atol=0)
    torch.testing.assert_close(head(features), restored(features), rtol=0, atol=0)
