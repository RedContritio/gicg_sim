"""Recovery keeps earlier candidates and rejects incomplete combined evidence."""

import pytest

from tools.experiments.semantic_training.recover_curriculum import merge_iterations


def test_keeps_earlier_best_and_breaks_ties_by_earliest():
    before = [dict(iteration=1, dev_score=0.65), dict(iteration=2, dev_score=0.55)]
    after = [dict(iteration=3, dev_score=0.65)]
    rows, chosen = merge_iterations(before, after, 3)
    assert len(rows) == 3 and chosen['iteration'] == 1


@pytest.mark.parametrize('indices', [[1, 3], [1, 2, 2], [2, 1, 3]])
def test_rejects_bad_round_sequence(indices):
    with pytest.raises(ValueError, match='training rounds'):
        merge_iterations([dict(iteration=i, dev_score=0.6) for i in indices], [], 3)
