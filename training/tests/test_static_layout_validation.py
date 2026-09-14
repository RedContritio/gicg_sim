from types import SimpleNamespace

import numpy as np
import pytest

from training.core.network.obs_layout import validate_static_layout
from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE, OBS_DEFINITION_LINK_SLOTS, OBS_MAX_CHARS


def test_old_hook_stride_rejects_new_engine_observation():
    cfg = SimpleNamespace(n_counter_slots=1832, n_hooks=900, max_ops_per_hook=64, fields_per_op=5)
    legacy_size = 1832 * 3 + OBS_CHAR_SKILL_REFS_SIZE + 900 * 128 * 5 + 2 * OBS_MAX_CHARS
    size = legacy_size + OBS_DEFINITION_LINK_SLOTS
    with pytest.raises(ValueError, match='layout mismatch'):
        validate_static_layout(np.zeros(size, dtype=np.int32), cfg)
    cfg.max_ops_per_hook = 128
    validate_static_layout(np.zeros(size, dtype=np.int32), cfg)
    with pytest.raises(ValueError, match='layout mismatch'):
        validate_static_layout(np.zeros(legacy_size, dtype=np.int32), cfg)
