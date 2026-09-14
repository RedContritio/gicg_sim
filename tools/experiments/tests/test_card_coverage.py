"""Real engine coverage audit with independent D2 policies."""

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.card_coverage import game
from tools.experiments.semantic_training.teams import eval_cases
from training.core.config.loader import load_cfg


def test_card_audit_records_real_legal_deck_and_play_opportunities():
    config = 'configs/dmc/curriculum_l6.toml'
    ev.initialize(config, 'teacher-d2')
    case = eval_cases(load_cfg(config), 176100, 15)[0]
    row = game((0, 0, case, 176100))
    assert sum(row['starting'].values()) == 30
    assert max(row['starting'].values()) <= 2
    assert row['win'] in (0, 1)
    assert set(row['used']) <= set(row['legal']) <= set(row['seen'])
    assert row['legal'] and row['used']
