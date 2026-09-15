"""Retention-arm mechanics: freezing, phase switching, and gradient gating."""

import copy

import pytest
import torch

from tools.experiments.semantic_training import retention_arms
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_lessons import build_pair, tasks
from tools.experiments.semantic_training.retention_arms import (
    ArmSpec,
    anchor_kl,
    apply_trainable,
    arm_specs,
    policy_trainable_names,
    run_arm,
    trainable_parameters,
)
from tools.experiments.semantic_training.rule_auxiliary import attach
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


CONFIG = 'configs/dmc/native_starter.toml'
CATALOG = 'configs/rule_validation/native_variants.toml'
FROZEN_LEGACY = 'base.counter_encoder.value_proj.weight'


def agent_config():
    return AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(load_cfg(CONFIG).paradigm).agent)


@pytest.fixture(scope='module')
def pairs():
    torch.set_num_threads(1)
    jobs = [
        job for job in tasks(CONFIG, CATALOG, vars(agent_config()), seed=95000, contexts=2) if job['split'] == 'train'
    ]
    built = [build_pair(job) for job in jobs[:2]]
    assert built and all(pair['split'] == 'train' for pair in built)
    return built


@pytest.fixture
def make_agent():
    def build():
        agent = SemanticAgent(agent_config())
        attach(agent)
        return agent

    return build


def teacher_rows(pairs):
    rows = [{'obs': row['obs'], 'tied': [row['action']]} for pair in pairs for row in pair['rows']]
    assert rows
    return rows


def policy_state(agent):
    return {key: value.clone() for key, value in agent.net.state_dict().items()}


def head_state(agent):
    return {key: value.clone() for key, value in agent.rule_head.state_dict().items()}


def drifted(before, after):
    return any(not torch.equal(before[key], after[key]) for key in before)


def test_trainable_names_respect_the_networks_own_freezes(make_agent):
    agent = make_agent()
    names = policy_trainable_names(agent)
    assert FROZEN_LEGACY not in names, 'legacy identity encoders must stay out of the trainable set'

    apply_trainable(agent, names, False)
    assert not trainable_parameters(agent)
    apply_trainable(agent, names, True)
    still_frozen = {name for name, p in agent.net.named_parameters() if not p.requires_grad}
    assert FROZEN_LEGACY in still_frozen, 'reviving the frozen legacy encoders would be a silent compat break'
    assert trainable_parameters(agent)


def test_anchor_kl_is_zero_for_identical_policies_and_stays_differentiable(make_agent, pairs):
    agent = make_agent()
    anchor = copy.deepcopy(agent.net).eval().requires_grad_(False)
    kl = anchor_kl(agent, anchor, teacher_rows(pairs))
    assert float(kl.detach()) == pytest.approx(0.0, abs=1e-6)
    assert kl.requires_grad


def test_frozen_arm_leaves_the_policy_bit_identical(make_agent, pairs):
    agent = make_agent()
    policy_before, head_before = policy_state(agent), head_state(agent)
    _, report = run_arm(agent, arm_specs()['frozen'], pairs, teacher_rows(pairs), steps=3, seed=1)
    assert not drifted(policy_before, agent.net.state_dict())
    assert drifted(head_before, agent.rule_head.state_dict()), "the head is this arm's only trainable surface"
    assert report['undefined_cos'] >= 1, 'a head-only arm trains no shared parameter, so no cosine exists'


def test_full_arm_changes_the_policy_and_traces_a_cosine(make_agent, pairs):
    agent = make_agent()
    policy_before = policy_state(agent)
    _, report = run_arm(agent, arm_specs()['full'], pairs, teacher_rows(pairs), steps=3, seed=1)
    assert drifted(policy_before, agent.net.state_dict())
    assert report['trace'] and report['trace'][0]['step'] == 1
    assert report['trace'][0]['cos'] is not None


def test_probe_then_finetune_records_the_phase_change(make_agent, pairs):
    agent = make_agent()
    policy_before = policy_state(agent)
    _, report = run_arm(agent, arm_specs()['probe_then_finetune'], pairs, teacher_rows(pairs), steps=4, seed=1)
    assert report['probe_steps'] == 2
    assert report['probe_exit'] is not None, 'the phase change must be measured, not assumed'
    assert report['frozen_at_end'] is False
    assert drifted(policy_before, agent.net.state_dict())


def test_binary_gate_drops_only_the_shared_policy_contribution(monkeypatch, make_agent, pairs):
    """The gate must cancel the auxiliary *policy* gradient while the head keeps learning.

    Folding the gate into a scalar loss weight instead would silently freeze the head,
    because the head is trained by the auxiliary loss alone.
    """
    rows = teacher_rows(pairs)
    spec = ArmSpec('gate_probe', 'all', 3e-4, gate='binary')
    monkeypatch.setattr(retention_arms, 'policy_gradient_cosine', lambda *a, **k: -1.0)

    blocked = make_agent()
    policy_before, head_before = policy_state(blocked), head_state(blocked)
    _, report = run_arm(blocked, spec, pairs, rows, steps=3, seed=1)
    assert report['gate_blocks'] == 3
    assert not drifted(policy_before, blocked.net.state_dict())
    assert drifted(head_before, blocked.rule_head.state_dict())

    monkeypatch.setattr(retention_arms, 'policy_gradient_cosine', lambda *a, **k: 1.0)
    allowed = make_agent()
    policy_before = policy_state(allowed)
    _, allowed_report = run_arm(allowed, spec, pairs, rows, steps=3, seed=1)
    assert allowed_report['gate_blocks'] == 0
    assert drifted(policy_before, allowed.net.state_dict())


def test_arm_specs_and_input_validation(make_agent, pairs):
    specs = arm_specs()
    assert set(specs) == {'full', 'frozen', 'probe_then_finetune', 'full_lowlr', 'replay', 'anchored'}
    assert specs['full'].learning_rate > specs['full_lowlr'].learning_rate
    assert specs['frozen'].trainable == 'head' and specs['full'].trainable == 'all'
    assert specs['anchored'].gate == 'binary' and specs['full'].gate == 'off'

    agent, rows = make_agent(), teacher_rows(pairs)
    with pytest.raises(ValueError, match='unsupported gate'):
        run_arm(agent, ArmSpec('bad', 'all', 3e-4, gate='weighted'), pairs, rows, steps=1)
    with pytest.raises(ValueError, match='steps must be positive'):
        run_arm(agent, specs['full'], pairs, rows, steps=0)
    with pytest.raises(ValueError, match='requires teacher rows'):
        run_arm(agent, specs['replay'], pairs, [], steps=1)
    with pytest.raises(ValueError, match='invalid diagnostic cadence'):
        run_arm(agent, specs['full'], pairs, rows, steps=1, diag_every=0)
