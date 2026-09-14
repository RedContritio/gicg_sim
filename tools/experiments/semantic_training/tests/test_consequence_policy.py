"""The experimental connection preserves initial behavior and learns from rewards."""

import copy

import torch
from torch import nn
import pytest

from tools.experiments.semantic_training.consequence_policy import ConsequencePolicyNet
from tools.experiments.semantic_training.rule_auxiliary import RuleHead


class Backbone(nn.Module):
    def __init__(self):
        super().__init__()
        self.hook_encoder = nn.Linear(4, 4)
        self.dropout = nn.Dropout(0.5)

    def forward(self, batch, *, return_actions=False):
        state = self.dropout(self.hook_encoder(batch['state']))
        actions = batch['actions']
        return (state[:, None] * actions).sum(-1), state, actions


def test_zero_residual_preserves_scores_and_only_residual_receives_reward_gradient():
    torch.manual_seed(19)
    base, head = Backbone().eval(), RuleHead(4)
    batch = {'state': torch.randn(2, 4), 'actions': torch.randn(2, 3, 4)}
    expected = base(batch)[0].detach()
    model = ConsequencePolicyNet(base, head, 4)
    model.train()
    assert not base.training and not head.training
    torch.testing.assert_close(model(batch), expected, rtol=0, atol=0)
    optimizer = torch.optim.SGD(model.residual.parameters(), lr=0.1)
    loss = -model(batch).log_softmax(-1)[:, 0].mean()
    loss.backward()
    assert model.residual[-1].weight.grad.abs().sum() > 0
    assert all(p.grad is None for p in base.parameters())
    assert all(p.grad is None for p in head.parameters())
    optimizer.step()
    assert not torch.equal(model(batch), expected)


def test_control_ignores_predictions_and_candidate_uses_them_after_connection_learns():
    torch.manual_seed(23)
    base, head = Backbone(), RuleHead(4)
    candidate = ConsequencePolicyNet(base, head, 4)
    control = copy.deepcopy(candidate)
    control.use_consequences = False
    batch = {'state': torch.randn(2, 4), 'actions': torch.randn(2, 3, 4)}
    with torch.no_grad():
        candidate.residual[-1].weight.fill_(0.2)
        control.residual.load_state_dict(candidate.residual.state_dict())
    before, control_before = candidate(batch).detach(), control(batch).detach()
    with torch.no_grad():
        head.layers[-1].bias.add_(2)
        control.rule_head.layers[-1].bias.add_(2)
    assert not torch.allclose(candidate(batch), before)
    torch.testing.assert_close(control(batch), control_before, rtol=0, atol=0)


def test_real_engine_cached_inference_matches_training_and_initial_policy(tmp_path):
    from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
    from tools.experiments.semantic_training.rule_lessons import trio_case
    from tools.experiments.semantic_training.rule_probe import variant
    from training.core.config.loader import load_cfg
    from training.core.network import AgentConfig
    from training.paradigms.dmc.config import DMCParadigmConfig

    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    data = tmp_path / 'variant'
    variant(cfg.scenario.data_dir, data, (2, 6))
    env, _ = trio_case(cfg, data, 94510, 7)
    try:
        agent.game_start(env.static_obs)
        original = agent.logits(env)
        agent.net = ConsequencePolicyNet(agent.net, RuleHead(shape.d_model), shape.d_model)
        torch.testing.assert_close(agent.logits(env), original, rtol=0, atol=0)
        obs = agent.observation(env)
        scores = agent.net(batch_observations([obs], shape, 'cpu'))[0, : len(original)]
        torch.testing.assert_close(scores, original, rtol=1e-5, atol=1e-5)
    finally:
        env.close()


def test_unified_loader_restores_residual_and_requires_explicit_arm(tmp_path):
    from tools.experiments.semantic_training.agent import SemanticAgent
    from tools.experiments.semantic_training.consequence_policy import FORMAT
    from tools.experiments.semantic_training.player_loader import load_semantic_agent
    from training.core.artifact_io import save_checkpoint
    from training.core.network import AgentConfig

    cfg = AgentConfig(n_counter_slots=128, n_hooks=32, max_ops_per_hook=16, max_actions=64)
    agent = SemanticAgent(cfg)
    model = ConsequencePolicyNet(agent.net, RuleHead(cfg.d_model), cfg.d_model, use_consequences=False)
    with torch.no_grad():
        model.residual[-1].weight.fill_(0.125)
    payload = dict(format=FORMAT, shape=vars(cfg), net=model.state_dict(), use_consequences=False)
    path = tmp_path / 'policy.pt'
    save_checkpoint(payload, path)
    restored = load_semantic_agent(str(path))
    assert restored.net.use_consequences is False
    assert all(not p.requires_grad for p in restored.net.backbone.parameters())
    for key, tensor in model.state_dict().items():
        torch.testing.assert_close(restored.net.state_dict()[key], tensor)
    del payload['use_consequences']
    save_checkpoint(payload, path)
    with pytest.raises(ValueError, match='explicit boolean'):
        load_semantic_agent(str(path))
