"""Real-engine oracle and isolated counterfactual source checks."""

import hashlib
from pathlib import Path

import pytest
import numpy as np

from tools.experiments.semantic_training.rule_probe import ProbeAgent, case, oracle, variant


@pytest.mark.parametrize('indirect', [False, True])
def test_counterfactual_swaps_immediate_winner_without_touching_source(tmp_path, indirect):
    source = Path('data/pools/native_latest/characters/凯亚/凯亚_仪典剑术.lua')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    signatures = []
    for i, damages in enumerate([(10, 1), (1, 10)]):
        data = tmp_path / str(i)
        signatures.append(variant('data', data, damages, indirect))
        env, indices = case(data, 93700, 7)
        try:
            view = env.export_view()
            assert oracle(env, indices) == i
            assert env.export_view() == view
            assert not env.done
            assert not list(env._engine.hand_refs(0))
            assert not list(env._engine.hand_refs(1))
        finally:
            env.close()
    assert signatures[0] != signatures[1]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_empty_card_graph_supports_real_model_inference(tmp_path):
    import torch
    from training.core.config.loader import load_cfg
    from training.core.network import AgentConfig
    from training.paradigms.dmc.config import DMCParadigmConfig

    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    agent = ProbeAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    variant('data', tmp_path, (10, 1))
    env, _ = case(tmp_path, 93700, 7)
    try:
        agent.game_start(env.static_obs)
        assert agent.observation(env)['card_links'].shape == (0, 2)
        assert torch.isfinite(agent.logits(env)).all()
    finally:
        env.close()


def test_changed_damage_hooks_are_linked_to_their_own_skill(tmp_path):
    from training.core.config.loader import load_cfg
    from training.core.network import AgentConfig
    from training.paradigms.dmc.config import DMCParadigmConfig

    cfg = load_cfg('configs/dmc/native_starter.toml')
    agent = ProbeAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    observations = []
    for i, damages in enumerate([(10, 1), (1, 10)]):
        data = tmp_path / str(i)
        variant('data', data, damages)
        env, indices = case(data, 93700, 7)
        try:
            agent.game_start(env.static_obs)
            obs = agent.observation(env)
            observations.append(obs)
            assert indices == [[0], [1]]
        finally:
            env.close()
    a, b = observations
    changed = set(np.where(np.any(a['hook_ir'] != b['hook_ir'], axis=(1, 2)))[0])
    assert len(changed) == 4  # Two skills on each mirror actor.
    linked_changes = []
    for canonical in a['action_refs'][:2, 1]:
        effects = {effect for source, effect in a['skill_links'] if source == canonical}
        linked_changes.append(effects & changed)
    assert all(len(s) == 1 for s in linked_changes)
    assert linked_changes[0].isdisjoint(linked_changes[1])
