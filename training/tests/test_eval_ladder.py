"""Evaluation ladder composition and reproducible mixture branches."""

import pytest

from tools.experiments.eval_ladder import BASELINES, MIXED, MixedD1, make_baseline


def test_mixed_policy_reproducible_and_uses_both_branches():
    class Player:
        def __init__(self, choice):
            self.choice = choice

        def select_action(self, env):
            return self.choice

    def sequence():
        mixed = MixedD1(19)
        mixed.random, mixed.greedy = Player(0), Player(1)
        return [mixed.select_action(None) for _ in range(100)]

    assert sequence() == sequence()
    assert set(sequence()) == {0, 1}


def test_registry_preserves_d1_d2_and_rejects_unknown():
    assert len(BASELINES) == 5 and MIXED in BASELINES
    assert make_baseline('F1-D1', 41, {}).cfg.depth == 1
    assert make_baseline('F1-D2', 41, {}).cfg.depth == 2
    with pytest.raises(ValueError, match='unknown'):
        make_baseline('typo', 41, {})


def test_crossplay_is_reproducible_and_paired():
    from tools.experiments.calibrate_ladder import play_pair
    from training.core.config.loader import load_cfg
    from training.paradigms.dmc._opponent import RandomPlayer

    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    one = play_pair(cfg, RandomPlayer, RandomPlayer, 2, 113000)
    two = play_pair(cfg, RandomPlayer, RandomPlayer, 2, 113000)
    assert one == two
    assert one['games'] == 4 and len(set(one['layout_seeds'])) == 2
    assert one['wins'] + one['draws'] + one['losses'] == 4
