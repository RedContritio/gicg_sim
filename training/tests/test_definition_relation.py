"""Canonical definition-link schema and aggregation regression tests."""

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from training.core.network.definition_relation import DefinitionRelation
from training.core.network.obs_layout import validate_static_layout
from training.core.network.static_links import parse_definition_links_np
from training.core.obs_constants import (
    OBS_CHAR_ELEMENT_SLOTS,
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_DEFINITION_LINK_SCHEMA_VERSION,
    OBS_DEFINITION_LINK_SLOTS,
)


CFG = SimpleNamespace(n_counter_slots=3, n_hooks=4, max_ops_per_hook=2, fields_per_op=5)


def _static() -> tuple[np.ndarray, int]:
    body = CFG.n_counter_slots * 3 + OBS_CHAR_SKILL_REFS_SIZE + CFG.n_hooks * 2 * 5 + OBS_CHAR_ELEMENT_SLOTS
    obs = np.zeros(body + OBS_DEFINITION_LINK_SLOTS, dtype=np.float32)
    obs[body] = OBS_DEFINITION_LINK_SCHEMA_VERSION
    return obs, body


def test_static_definition_links_required_and_parsed() -> None:
    static, offset = _static()
    static[offset + 1] = 2
    static[offset + 2 : offset + 6] = [2, 0, 1, 3]
    validate_static_layout(static, CFG)
    np.testing.assert_array_equal(
        parse_definition_links_np(static, n_counter_slots=3, n_hooks=4, max_ops_per_hook=2, fields_per_op=5),
        [[2, 0], [1, 3]],
    )
    with pytest.raises(ValueError, match='layout mismatch'):
        validate_static_layout(static[:-OBS_DEFINITION_LINK_SLOTS], CFG)


def test_static_definition_link_schema_rejects_unknown_version() -> None:
    static, offset = _static()
    static[offset] = OBS_DEFINITION_LINK_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match='unsupported definition-link schema'):
        parse_definition_links_np(static, n_counter_slots=3, n_hooks=4, max_ops_per_hook=2, fields_per_op=5)


@pytest.mark.parametrize('bad_count', [-1, 16385, 1.5])
def test_static_definition_link_count_rejects_malformed_values(bad_count: float) -> None:
    static, offset = _static()
    static[offset + 1] = bad_count
    with pytest.raises(ValueError, match='definition-link count'):
        parse_definition_links_np(static, n_counter_slots=3, n_hooks=4, max_ops_per_hook=2, fields_per_op=5)


def test_definition_relation_uses_edges_and_backpropagates() -> None:
    torch.manual_seed(7)
    relation = DefinitionRelation(8)
    hooks = torch.randn(2, 4, 8, requires_grad=True)
    links = torch.tensor([[[0, 1], [0, 2]], [[3, 0], [-1, -1]]])
    out = relation(hooks, links)
    assert out.shape == hooks.shape
    out.square().sum().backward()
    assert hooks.grad is not None and hooks.grad.abs().sum() > 0
    assert all(p.grad is not None and p.grad.abs().sum() > 0 for p in relation.parameters())


@pytest.mark.parametrize('links', [[[0, 4]], [[-1, 0]], [[-2, -2]]])
def test_definition_relation_rejects_invalid_rows(links: list[list[int]]) -> None:
    with pytest.raises(ValueError, match='definition link'):
        DefinitionRelation(8)(torch.randn(1, 4, 8), torch.tensor([links]))
