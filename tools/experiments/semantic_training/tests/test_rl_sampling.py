import random

import pytest

from tools.experiments.semantic_training.rl_sampling import stratified_indices


def test_stratified_indices_downsamples_to_requested_mix_without_replacement():
    rows = [{'decision_type': 'reroll'} for _ in range(80)] + [{'decision_type': 'ordinary'} for _ in range(20)]
    selected = stratified_indices(rows, random.Random(7), 1 / 3)
    assert len(selected) == len(set(selected)) == 30
    assert sum(rows[index]['decision_type'] == 'reroll' for index in selected) == 10
    assert sum(rows[index]['decision_type'] == 'ordinary' for index in selected) == 20


def test_stratified_indices_uses_all_rows_when_only_one_type_exists():
    rows = [{'decision_type': 'ordinary'} for _ in range(8)]
    assert sorted(stratified_indices(rows, random.Random(3), 1 / 3)) == list(range(8))


@pytest.mark.parametrize('fraction', [0, 1, -0.1, 1.1])
def test_stratified_indices_rejects_invalid_fraction(fraction):
    with pytest.raises(ValueError, match='between zero and one'):
        stratified_indices([], random.Random(1), fraction)
