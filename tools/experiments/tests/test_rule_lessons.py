"""Disjoint diagnostic splits and actual native 3v3 rule-label training path."""

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.learn_rules import assess, logits_for
from tools.experiments.semantic_training.rule_lessons import damage_oracle, specifications, trio_case
from tools.experiments.semantic_training.rule_probe import variant
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def test_rule_lesson_literal_values_are_disjoint():
    train, heldout = specifications()
    assert {v for pair in train for v in pair}.isdisjoint({v for pair in heldout for v in pair})
    assert all(low < 10 <= high for low, high in train + heldout)


def test_trio_oracle_flips_and_reaches_numeric_and_definition_parameters(tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(93800)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    agent = SemanticAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    rows, views = [], []
    for i, damages in enumerate([(10, 1), (1, 10)]):
        data = tmp_path / str(i)
        variant('data', data, damages)
        env, indices = trio_case(cfg, data, 93800, 93801)
        try:
            views.append(env.export_view())
            chosen, amounts = damage_oracle(env, indices)
            assert chosen == i
            assert amounts == list(damages)
            assert views[-1] == env.export_view()
            for side in (0, 1):
                assert len(env._engine.hand_refs(side)) + len(env._engine.deck_refs(side)) == 30
            agent.game_start(env.static_obs)
            rows.append(
                dict(
                    obs=agent.observation(env),
                    split='train',
                    mode='trio',
                    tied=indices[chosen],
                    candidates=[a for group in indices for a in group],
                )
            )
        finally:
            env.close()
    assert views[0] == views[1]
    logp = logits_for(agent, rows).log_softmax(-1)
    loss = torch.stack([-logp[i, row['tied']].mean() for i, row in enumerate(rows)]).mean()
    loss.backward()
    for p in (
        agent.net.hook_encoder.literal_projection[0].weight,
        agent.net.base.definition_relation.message[0].weight,
    ):
        assert torch.isfinite(p.grad).all() and p.grad.abs().sum() > 0
    assert assess(agent, rows)['train/trio']['cases'] == 2
