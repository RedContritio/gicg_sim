"""Real trajectory update and optimizer restoration for consequence residuals."""

import random

import pytest
import torch

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.consequence_export import export
from tools.experiments.semantic_training.consequence_policy import FORMAT
from tools.experiments.semantic_training.consequence_rl import matched_initials
from tools.experiments.semantic_training.player_loader import FORMAT as PARENT_FORMAT, load_semantic_agent
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import update
from tools.experiments.semantic_training.rule_auxiliary import RuleHead
from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_matched_export_real_rollout_update_and_optimizer_restore(tmp_path):
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    torch.manual_seed(95400)
    original = SemanticAgent(shape)
    parent = tmp_path / 'parent.pt'
    save_checkpoint(
        dict(
            format='paired-consequence/1.0.0',
            parent_format=PARENT_FORMAT,
            shape=vars(shape),
            net=original.net.state_dict(),
            rule_head=RuleHead(shape.d_model).state_dict(),
        ),
        parent,
    )
    root = export(parent, tmp_path / 'matched')
    assert set(matched_initials(root)) == {'candidate', 'control'}
    a, b = [load_checkpoint(root / f'{arm}.pt', weights_only=False) for arm in ('candidate', 'control')]
    for key in a['net']:
        torch.testing.assert_close(a['net'][key], b['net'][key], rtol=0, atol=0)
    assert a['use_consequences'] and not b['use_consequences']
    with pytest.raises(FileExistsError):
        export(parent, root)
    ev.initialize('configs/dmc/native_starter.toml', root / 'candidate.pt', 1)
    directory = tmp_path / 'rollout'
    directory.mkdir()
    record = episode((1, 0, str(directory), 95400))
    rows = torch.load(record['path'], weights_only=False)[:32]
    assert rows and all(r['reward'] in (-1, 0, 1) for r in rows)
    agent = load_semantic_agent(root / 'candidate.pt')
    anchor = load_semantic_agent(root / 'candidate.pt')
    optimizer = torch.optim.AdamW([p for p in agent.net.parameters() if p.requires_grad], lr=1e-5)
    metrics = update(agent, anchor, optimizer, rows, [0, 0], random.Random(1), epochs=1)
    assert metrics['updates'] > 0
    assert not torch.equal(agent.net.residual[-1].weight, a['net']['residual.2.weight'])
    for key, value in agent.net.state_dict().items():
        if not key.startswith('residual.'):
            torch.testing.assert_close(value, a['net'][key], rtol=0, atol=0)
    checkpoint = tmp_path / 'resume.pt'
    save_checkpoint(
        dict(
            format=FORMAT,
            shape=vars(shape),
            net=agent.net.state_dict(),
            use_consequences=True,
            optimizer=optimizer.state_dict(),
        ),
        checkpoint,
    )
    restored = load_semantic_agent(checkpoint)
    restored_opt = torch.optim.AdamW([p for p in restored.net.parameters() if p.requires_grad], lr=1e-5)
    restored_opt.load_state_dict(load_checkpoint(checkpoint, weights_only=False)['optimizer'])
    for model, opt in ((agent, optimizer), (restored, restored_opt)):
        update(model, anchor, opt, rows, [0, 0], random.Random(2), epochs=1)
    for key, value in agent.net.state_dict().items():
        torch.testing.assert_close(value, restored.net.state_dict()[key], rtol=0, atol=0)
    b['net']['residual.2.weight'].fill_(1)
    save_checkpoint(b, root / 'control.pt')
    with pytest.raises(ValueError, match='tensors differ'):
        matched_initials(root)
