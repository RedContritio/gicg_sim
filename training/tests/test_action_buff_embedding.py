import pytest
import torch

from training.core.network.action_buff_embedding import selected_buff_embeddings
from training.core.obs_constants import OBS_BUFF_ROWS


def test_support_replacement_targets_own_slot_not_enemy_or_buff():
    rows = torch.zeros(1, 4, 16)
    rows[0, :, 0] = 1
    rows[0, :, 12] = torch.tensor([0, 1, 1, 1])
    rows[0, :, 6] = torch.tensor([0, 0, 1, 0])
    rows[0, 3, 1] = 1  # enemy support in its own slot zero
    tokens = torch.tensor([[[1.0, 0.0], [0.0, 2.0], [3.0, 4.0], [99.0, 99.0]]])
    refs = torch.tensor([[-2, -2 - OBS_BUFF_ROWS, -3 - OBS_BUFF_ROWS]])
    torch.testing.assert_close(selected_buff_embeddings(refs, rows, tokens), tokens[:, :3])


def test_selected_buff_combines_its_hooks_and_preserves_gradient():
    rows = torch.zeros(1, 4, 16)
    rows[0, :, 0] = 1
    rows[0, :, 6] = torch.tensor([0, 1, 1, 0])
    rows[0, 3, 12] = 1  # support entity, not another hook of buff zero
    tokens = torch.tensor([[[1.0, 0.0], [0.0, 2.0], [0.0, 4.0], [99.0, 99.0]]], requires_grad=True)
    refs = torch.tensor([[-2, -3, -1, 0]])
    actual = selected_buff_embeddings(refs, rows, tokens)
    torch.testing.assert_close(actual, torch.tensor([[[1.0, 0.0], [0.0, 3.0], [0.0, 0.0], [0.0, 0.0]]]))
    actual.sum().backward()
    torch.testing.assert_close(tokens.grad, torch.tensor([[[1.0, 1.0], [0.5, 0.5], [0.5, 0.5], [0.0, 0.0]]]))


def test_selected_buff_follows_position_when_rows_are_permuted():
    rows = torch.zeros(2, 4, 16)
    rows[:, :3, 0] = 1
    rows[:, :, 6] = torch.tensor([2, 0, 2, 0])
    tokens = torch.randn(2, 4, 8)
    refs = torch.tensor([[-4, -2], [-2, -4]])
    expected = selected_buff_embeddings(refs, rows, tokens)
    order = torch.tensor([2, 3, 0, 1])
    torch.testing.assert_close(selected_buff_embeddings(refs, rows[:, order], tokens[:, order]), expected)


def test_missing_buff_target_fails_instead_of_aliasing_another_action():
    with pytest.raises(ValueError, match='requires live'):
        selected_buff_embeddings(torch.tensor([[-2]]), None, None)
    rows = torch.zeros(1, 3, 16)
    rows[0, 0, 0] = 1
    tokens = torch.randn(1, 3, 8)
    for missing in [-3, -100]:
        with pytest.raises(ValueError, match='absent'):
            selected_buff_embeddings(torch.tensor([[missing]]), rows, tokens)
