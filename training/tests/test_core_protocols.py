"""Core protocol contract tests.

Verify runtime_checkable Protocols accept conformant mock impls + reject
non-conformant ones. PipelineState transition methods sanity-checked."""

from __future__ import annotations

import numpy as np

from training.core.protocols import (
    Batch,
    Buffer,
    Collector,
    CollectorOutput,
    EpisodePolicy,
    EpisodeRecord,
    EpisodeSpec,
    LossComputer,
    LossResult,
    NetworkProvider,
    Paradigm,
    PipelineState,
    StepPlan,
    Transition,
)


class _MockProvider:
    def forward(self, obs, mask):
        return {'logits': [0.0]}

    def update_weights(self, version_tag=None):
        return 1

    def current_version(self):
        return 1

    def close(self):
        pass


class _MockPolicy:
    def reset(self):
        pass

    def act(self, obs, mask, provider):
        return 0, {}


class _MockBuffer:
    capacity = 100

    def push(self, batch):
        pass

    def sample(self, batch_size, rng=None):
        return Batch(data={}, weights=None, size=batch_size)

    def clear(self):
        pass

    def __len__(self):
        return 0

    def state_dict(self):
        return {}

    def load_state_dict(self, sd):
        pass


def test_network_provider_runtime_checkable():
    assert isinstance(_MockProvider(), NetworkProvider)


def test_episode_policy_runtime_checkable():
    assert isinstance(_MockPolicy(), EpisodePolicy)


def test_buffer_runtime_checkable():
    assert isinstance(_MockBuffer(), Buffer)


def test_non_conformant_rejected():
    class Bad:
        pass

    assert not isinstance(Bad(), NetworkProvider)
    assert not isinstance(Bad(), Buffer)


def test_pipeline_state_fresh_has_rng():
    s = PipelineState.fresh(seed=42)
    assert s.step == 0
    assert 'master' in s.rng_state


def test_pipeline_state_transitions():
    s = PipelineState.fresh(seed=7)
    out = CollectorOutput(transitions=[None, None, None], episode_stats=[{'r': 1}])
    s.after_collect(out)
    assert s.total_transitions == 3
    assert s.total_episodes == 1
    s.after_train({'loss': 0.5})
    assert s.train_steps == 1
    s.after_eval()
    assert s.last_eval_at_step == 0
    s.after_ckpt()
    assert s.last_ckpt_at_step == 0


def test_pipeline_state_advance():
    s = PipelineState.fresh(seed=7)
    plan = StepPlan(collect=True, n_episodes=1, train=False, n_train_batches=0, batch_size=8, eval=False)
    s.advance(plan)
    assert s.step == 1


def test_pipeline_state_snapshot_round_trip_keys():
    s = PipelineState.fresh(seed=1)
    snap = s.snapshot()
    for k in ('step', 'total_episodes', 'total_transitions', 'train_steps', 'weights_version'):
        assert k in snap


def test_dataclass_construct_paths():
    """Smoke: every public dataclass constructable from minimal args."""
    t = Transition(obs=None, action=0, legal_mask=None, reward=0.0, done=False)
    assert t.action == 0
    r = EpisodeRecord(transitions=[], final_reward=1.0, length=0, winner=0, opponent_id='random', scenario_seed=1)
    assert r.opponent_id == 'random'
    b = Batch(data={}, weights=None, size=0)
    assert b.size == 0
    lr = LossResult(loss=None, breakdown={})
    assert lr.breakdown == {}
    sp = StepPlan(collect=True, n_episodes=1, train=False, n_train_batches=0, batch_size=4, eval=False)
    assert sp.collect is True
    es = EpisodeSpec(scenario_seed=1, opponent_id='random')
    assert es.opponent_id == 'random'
