"""Acceptance audit rejects corrupted or incomplete evidence."""

from copy import deepcopy

import pytest

from tools.experiments.semantic_training.verify_curriculum import checked_panel


def panel():
    rows = [
        dict(
            index=i,
            side=side,
            layout=layout,
            matchup=f'pair{i % 15}',
            draw=0,
            win=int(i % 4 != 0),
            score=int(i % 4 != 0),
        )
        for i in range(720)
        for side in (0, 1)
        for layout in (0, 1)
    ]
    return dict(
        status='complete',
        checkpoint_sha256='frozen',
        seed=274000,
        opponent_depth=2,
        scenarios=720,
        layouts=2,
        score=0.75,
        games=rows,
    )


def test_recomputes_raw_score_and_rejects_changed_summary():
    p = panel()
    result = checked_panel(p, {'sha256': 'frozen'}, 274000, 2)
    assert result['passes'] and result['score'] == 0.75
    p['score'] = 0.9
    with pytest.raises(ValueError, match='summary score'):
        checked_panel(p, {'sha256': 'frozen'}, 274000, 2)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'layout', 'checkpoint'])
def test_rejects_invalid_final_evidence(change):
    p = deepcopy(panel())
    if change == 'missing':
        p['games'].pop()
    elif change == 'duplicate':
        p['games'][1] = p['games'][0]
    elif change == 'layout':
        p['games'][1]['win'] = p['games'][1]['score'] = 1
    else:
        p['checkpoint_sha256'] = 'changed'
    with pytest.raises(ValueError):
        checked_panel(p, {'sha256': 'frozen'}, 274000, 2)
