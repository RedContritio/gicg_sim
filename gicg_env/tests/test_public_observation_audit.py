"""Public transition settings survive raw obs -> normalized NN input."""

import numpy as np

from gicg_env import GicgEnv, OBS_COUNTER_SLOTS, OBS_META_SIZE
from training.core.step_encoding import parse_dynamic_np


def test_public_round_limit_and_roll_configuration_survive_normalization():
    with GicgEnv(['赤蝶'], ['墨客'], pool=['v_legacy'], card_pool=[], max_rounds=7, data_dir='data') as env:
        obs = env.reset(seed=42)
        # Read the same normalized observation used by policies.
        obs = env._get_obs()
        _, meta, _, _ = parse_dynamic_np(obs, OBS_COUNTER_SLOTS)
        assert meta.shape == (OBS_META_SIZE,)
        assert meta[5] == -1  # no player has declared end
        assert meta[6] == 7
        assert meta[9] == 0  # random roll, not a hidden fixed configuration
        np.testing.assert_array_equal(meta, obs[:OBS_META_SIZE])
