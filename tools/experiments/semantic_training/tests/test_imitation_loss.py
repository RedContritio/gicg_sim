import pytest
import torch

from tools.experiments.semantic_training.imitation_loss import imitation_loss


def test_all_actions_tied_preserves_existing_preferences():
    logits = torch.tensor([[4.0, 1.0, -2.0]], requires_grad=True)
    loss, _, _ = imitation_loss(logits, [[0, 1, 2]], 'set')
    loss.backward()
    assert abs(float(loss)) < 1e-6
    assert torch.allclose(logits.grad, torch.zeros_like(logits), atol=1e-6)


def test_set_likelihood_depends_on_total_mass_not_uniformity():
    for probabilities in ([0.8, 0.1, 0.1], [0.45, 0.45, 0.1]):
        logits = torch.tensor([probabilities]).log()
        loss, _, _ = imitation_loss(logits, [[0, 1]], 'set')
        assert float(loss) == pytest.approx(-torch.tensor(0.9).log().item())


def test_anchor_is_detached_and_penalizes_drift():
    logits = torch.tensor([[0.0, 2.0]], requires_grad=True)
    anchor = torch.tensor([[2.0, 0.0]], requires_grad=True)
    loss, fit, kl = imitation_loss(logits, [[0, 1]], 'set', anchor, 1.0)
    loss.backward()
    assert float(fit) == pytest.approx(0.0, abs=1e-6)
    assert float(kl) > 0
    assert logits.grad[0, 0] < 0
    assert anchor.grad is None


def test_uniform_default_retains_original_loss():
    logits = torch.tensor([[2.0, 0.0, -1.0]])
    loss, _, _ = imitation_loss(logits, [[0, 1]])
    assert torch.allclose(loss, -logits.log_softmax(-1)[0, :2].mean())
