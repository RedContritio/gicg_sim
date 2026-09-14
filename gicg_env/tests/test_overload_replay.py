"""Fixed action RNG reproduces the round-7 overload nil builtin regression."""

import numpy as np

from gicg_env.engine import GicgEngine


def test_seed29_overload_playthrough():
    engine = GicgEngine()
    rng = np.random.RandomState(29)
    try:
        engine.new_game(players=[['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']], seed=123, data_dir='data')
        for step in range(500):
            if engine.done:
                break
            kinds, _ = engine.get_legal_actions()
            assert len(kinds)
            result = engine.step(int(rng.randint(len(kinds))))
            if result == 0:
                kinds, _ = engine.get_legal_actions()
                assert len(kinds)
                engine.step_target(int(rng.randint(len(kinds))))
        assert engine.done, 'fixed regression trajectory did not terminate'
        assert step >= 74, 'regression never reached the previously failing prefix'
    finally:
        engine.close()
