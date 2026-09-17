"""Retention diagnostics compare exact updates and functional action ordering."""

import pytest
import torch

from tools.experiments.semantic_training.retention_metrics import (
    action_kind_name,
    average_rank_at,
    parameter_group,
    policy_probe,
    update_report,
)


def test_parameter_group_separates_shared_surfaces():
    assert parameter_group('base.hook_encoder.opcode_embed.weight') == 'hook_encoder'
    assert parameter_group('base.cross_layers.0.counter_ffn.0.weight') == 'cross_layers'
    assert parameter_group('base.state_proj.0.weight') == 'state_proj'
    assert parameter_group('base.heads.q.state_proj.0.weight') == 'q_head'
    assert parameter_group('base.dice_combo_proj.0.weight') == 'action_encoding'
    assert parameter_group('relation.0.weight') == 'semantic_encoders'


def test_update_report_aggregates_tensor_and_module_norms():
    reference = {'base.state_proj.0.weight': torch.zeros(2), 'relation.0.weight': torch.tensor([3.0])}
    candidate = {'base.state_proj.0.weight': torch.tensor([3.0, 4.0]), 'relation.0.weight': torch.tensor([3.0])}
    report = update_report(reference, candidate)
    assert report['tensors']['base.state_proj.0.weight']['delta_norm'] == pytest.approx(5.0)
    assert report['groups']['state_proj']['delta_norm'] == pytest.approx(5.0)
    assert report['groups']['semantic_encoders']['delta_norm'] == 0
    assert report['top_delta_norm'][0] == 'base.state_proj.0.weight'


def test_average_rank_uses_ties_and_direction():
    values = torch.tensor([1.0, 3.0, 3.0, 2.0])
    assert average_rank_at(values, 0) == pytest.approx(4.0)
    assert average_rank_at(values, 1) == pytest.approx(1.5)
    assert average_rank_at(values, 3) == pytest.approx(3.0)


def test_policy_probe_reports_kl_ordering_and_expert_metrics():
    reference = torch.tensor([[1.0, 2.0, 3.0, -1e9]])
    candidate = torch.tensor([[3.0, 2.0, 1.0, -1e9]])
    mask = torch.tensor([[True, True, True, False]])
    probe = policy_probe(
        reference,
        mask,
        candidate,
        mask,
        selected=torch.tensor([0]),
        tied=[{2}],
        temperature=1.0,
    )
    assert probe['kl'] > 0
    assert probe['top1_agreement'] == 0
    assert probe['spearman'] == pytest.approx(-1.0)
    assert probe['reference_selected_rank'] == pytest.approx(3.0)
    assert probe['candidate_selected_rank'] == pytest.approx(1.0)
    assert probe['candidate_tied_top1'] == 0


def test_policy_probe_is_identity_for_identical_q():
    q = torch.tensor([[1.0, 2.0, -1e9]])
    mask = torch.tensor([[True, True, False]])
    probe = policy_probe(q, mask, q, mask, temperature=0.5)
    assert probe['kl'] == pytest.approx(0.0)
    assert probe['top1_agreement'] == 1.0
    assert probe['top5_overlap'] == 1.0
    assert probe['spearman'] == pytest.approx(1.0)


def test_policy_probe_groups_rows_by_metadata():
    reference = torch.tensor([[1.0, 2.0], [3.0, 1.0]])
    candidate = torch.tensor([[1.0, 2.0], [1.0, 3.0]])
    mask = torch.ones(2, 2, dtype=torch.bool)
    probe = policy_probe(
        reference,
        mask,
        candidate,
        mask,
        selected=torch.tensor([1, 0]),
        groups={'kind': ['damage', 'heal'], 'field': ['enemy', 'own']},
        temperature=1.0,
    )
    assert probe['groups']['kind']['damage']['top1_agreement'] == 1.0
    assert probe['groups']['kind']['heal']['top1_agreement'] == 0.0
    assert probe['groups']['kind']['heal']['candidate_selected_rank'] == pytest.approx(2.0)
    assert probe['groups']['field']['enemy']['rows'] == 1
    assert probe['groups']['field']['own']['rows'] == 1


def test_action_kind_name_reads_selected_action_reference():
    observation = {'action_refs': [[4, 2, -1], [3, -1, -1]]}
    assert action_kind_name(observation, 0) == 'Tune'
    assert action_kind_name(observation, 1) == 'EndTurn'
    assert action_kind_name(observation, 2) == 'unknown'
