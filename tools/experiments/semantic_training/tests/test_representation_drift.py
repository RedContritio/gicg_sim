"""Representation/gradient drift diagnostics: exactness, invariances, and loud failures."""

import pytest
import torch

from tools.experiments.semantic_training.representation_drift import (
    cosine_similarity,
    linear_cka,
    model_digest,
    tensor_drift,
)


def features(seed, samples=24, width=5):
    return torch.randn(samples, width, generator=torch.Generator().manual_seed(seed))


def test_cka_is_one_for_identical_input_and_scale_invariant():
    x = features(1)
    assert linear_cka(x, x) == pytest.approx(1.0)
    assert linear_cka(x, x * 7.5) == pytest.approx(1.0)


def test_cka_is_low_for_unrelated_features_and_high_for_small_perturbation():
    x, unrelated = features(1), features(2)
    assert linear_cka(x, unrelated) < 0.5
    perturbed = x + 0.01 * features(3)
    assert linear_cka(x, perturbed) > 0.99


def test_cka_is_invariant_to_sample_permutation():
    x, y = features(1), features(4)
    order = torch.randperm(x.shape[0], generator=torch.Generator().manual_seed(9))
    assert linear_cka(x[order], y[order]) == pytest.approx(linear_cka(x, y))


def test_cka_rejects_malformed_input():
    with pytest.raises(ValueError, match='2-D'):
        linear_cka(torch.zeros(4), torch.zeros(4))
    with pytest.raises(ValueError, match='same number of samples'):
        linear_cka(torch.zeros(4, 3), torch.zeros(5, 3))
    with pytest.raises(ValueError, match='at least two samples'):
        linear_cka(torch.zeros(1, 3), torch.zeros(1, 3))
    with pytest.raises(ValueError, match='constant features'):
        linear_cka(torch.ones(4, 3), torch.ones(4, 3))


def test_tensor_drift_reports_mean_and_max_against_known_values():
    reference = {'w': torch.zeros(2), 'b': torch.zeros(1)}
    candidate = {'w': torch.tensor([1.0, -3.0]), 'b': torch.zeros(1)}
    drift = tensor_drift(reference, candidate)
    assert drift['tensors']['w'] == {'mean': pytest.approx(2.0), 'max': pytest.approx(3.0)}
    assert drift['tensors']['b'] == {'mean': 0.0, 'max': 0.0}
    assert drift['mean'] == pytest.approx(1.0)
    assert drift['max'] == pytest.approx(3.0)


def test_tensor_drift_is_zero_for_identical_state():
    reference = {'w': features(5, 3, 2)}
    drift = tensor_drift(reference, {key: value.clone() for key, value in reference.items()})
    assert drift['mean'] == 0.0 and drift['max'] == 0.0


@pytest.mark.skipif(not torch.cuda.is_available(), reason='requires CUDA')
def test_tensor_drift_compares_cpu_reference_to_cuda_candidate():
    reference = {'w': torch.zeros(2)}
    candidate = {'w': torch.tensor([1.0, -3.0], device='cuda')}
    drift = tensor_drift(reference, candidate)
    assert drift['tensors']['w'] == {'mean': pytest.approx(2.0), 'max': pytest.approx(3.0)}


def test_tensor_drift_rejects_structural_mismatch():
    with pytest.raises(ValueError, match='keys differ'):
        tensor_drift({'a': torch.zeros(2)}, {'b': torch.zeros(2)})
    with pytest.raises(ValueError, match='shape differs'):
        tensor_drift({'a': torch.zeros(2)}, {'a': torch.zeros(3)})
    with pytest.raises(ValueError, match='empty'):
        tensor_drift({}, {})


def test_cosine_similarity_bounds_and_zero_norm_is_undefined():
    assert cosine_similarity([torch.tensor([1.0, 0.0])], [torch.tensor([2.0, 0.0])]) == pytest.approx(1.0)
    assert cosine_similarity([torch.tensor([1.0, 0.0])], [torch.tensor([-1.0, 0.0])]) == pytest.approx(-1.0)
    assert cosine_similarity([torch.tensor([1.0, 0.0])], [torch.tensor([0.0, 5.0])]) == pytest.approx(0.0)
    # A zero-norm gradient is genuinely undefined, not orthogonal.
    assert cosine_similarity([torch.zeros(3)], [torch.ones(3)]) is None
    assert cosine_similarity([torch.zeros(3)], [torch.zeros(3)]) is None


def test_cosine_similarity_flattens_across_multiple_tensors():
    left = [torch.tensor([1.0]), torch.tensor([0.0])]
    right = [torch.tensor([3.0]), torch.tensor([0.0])]
    assert cosine_similarity(left, right) == pytest.approx(1.0)


def test_cosine_similarity_rejects_malformed_collections():
    with pytest.raises(ValueError, match='length'):
        cosine_similarity([torch.ones(2)], [torch.ones(2), torch.ones(2)])
    with pytest.raises(ValueError, match='empty'):
        cosine_similarity([], [])


def test_model_digest_handles_bfloat16_noncontiguous_tensors():
    class _Module(torch.nn.Module):
        def __init__(self, value):
            super().__init__()
            self.register_buffer('weight', value)

    value = torch.arange(12, dtype=torch.float32).reshape(3, 4).t().to(torch.bfloat16)
    assert not value.is_contiguous()
    agent = type('Agent', (), {'net': _Module(value), 'rule_head': _Module(value)})()
    digest = model_digest(agent)
    assert digest['net'] == digest['rule_head']
    assert len(digest['net']) == 64
