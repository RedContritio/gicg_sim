"""Auxiliary labels come from the engine and candidate costs/legality are hidden."""

import numpy as np
import torch

from tools.experiments.rule_state_data import collect
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig


def test_discount_and_eligibility_are_reachable_and_not_candidate_inputs():
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    agent = DmcAgent(AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent))
    rows = collect(agent, [600])
    assert len(rows) == 30
    assert {r['side'] for r in rows} == {0, 1}
    assert {r['cost'] for r in rows} == {0, 3}
    for r in rows:
        np.testing.assert_array_equal(r['labels'], [r['count'] == 3, r['fed'] != 0, r['fed'] != 1])
        np.testing.assert_array_equal(r['obs']['action_refs'], [[3, -1, -1]])
        assert r['obs']['action_payments'].sum() == 0
        assert r['obs']['n_legal'] == 1
