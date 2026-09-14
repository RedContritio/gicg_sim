"""The conditional task cannot be solved by fixed target or active-slot shortcuts."""

import numpy as np
import torch

from tools.experiments.target_data import collect
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig


def test_balanced_reachable_target_states():
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    agent = DmcAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    rows = collect(agent, [401])
    assert len(rows) == 8
    assert {(r['side'], r['wounded'], r['active']) for r in rows} == {
        (s, w, a) for s in (0, 1) for w in (0, 1) for a in (0, 1)
    }
    for row in rows:
        assert row['trace']
        assert row['obs']['n_legal'] == 2
        refs = row['obs']['action_refs']
        assert set(refs[:, 2]) == {0, 1}  # always own-first, including P1
        np.testing.assert_array_equal(row['utility'], (refs[:, 2] == row['wounded']).astype(float))
    assert sum(r['active'] == r['wounded'] for r in rows) == 4
