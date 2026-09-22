import random

import pytest
import torch

from tools.experiments.semantic_training.paired_counterfactual import (
    paired_preference_loss,
    paired_rollouts,
    reservoir_replace,
    sample_alternative_action,
)
from tools.experiments.semantic_training.paired_rl_rollout import aggregate_pair, should_collect_root


class _FakeEnv:
    def __init__(self, learner_side=0, tie=False, seed_log=None):
        self.learner_side = learner_side
        self.tie = tie
        self.seed_log = seed_log if seed_log is not None else []
        self.root_action = None
        self.acting_player = learner_side
        self.done = False
        self.winner = -1
        self.static_obs = {}

    def clone(self):
        return _FakeEnv(self.learner_side, self.tie, self.seed_log)

    def set_simulation_seed(self, seed):
        self.seed_log.append(seed)

    def step(self, action):
        if self.root_action is None:
            self.root_action = action
            self.acting_player = 1 - self.learner_side
            return
        self.done = True
        self.winner = 2 if self.tie else (self.learner_side if self.root_action else 1 - self.learner_side)

    def close(self):
        pass


class _FakePlayer:
    def __init__(self):
        self.rng = random.Random()

    def game_start(self, _static_obs):
        pass

    def select_action(self, _env):
        return 0


def test_paired_rollouts_use_common_seed_and_support_side_one():
    seed_log = []
    result = paired_rollouts(
        _FakeEnv(learner_side=1, seed_log=seed_log),
        1,
        0,
        _FakePlayer(),
        _FakePlayer(),
        learner_side=1,
        simulation_seeds=[17, 19],
        max_steps=4,
        decision_type='reroll',
    )
    assert seed_log == [17, 17, 19, 19]
    assert [row['simulation_seed'] for row in result['pairs']] == [17, 19]
    assert all(row['preference'] == 1 and row['decision_type'] == 'reroll' for row in result['pairs'])


def test_paired_rollouts_skip_ties():
    result = paired_rollouts(
        _FakeEnv(tie=True), 1, 0, _FakePlayer(), _FakePlayer(), learner_side=0, simulation_seeds=[3, 4]
    )
    assert result['pairs'] == []
    assert result['ties'] == 2


def test_reservoir_decision_keeps_one_replaceable_root():
    rng = random.Random(9)
    seen = 0
    retained = None
    for index in range(32):
        seen, replace = reservoir_replace(seen, rng)
        if replace:
            retained = index
    assert seen == 32
    assert retained in range(32)


def test_alternative_sampling_excludes_chosen_action():
    logits = torch.tensor([4.0, 2.0, 1.0])
    torch.manual_seed(12)
    assert sample_alternative_action(logits, chosen=1) != 1


def test_preference_loss_favors_the_preferred_action_and_anchor_kl_is_optional():
    mask = torch.tensor([[True, True, False]])
    anchor = torch.zeros(1, 3)
    good = torch.tensor([[3.0, 0.0, 0.0]], requires_grad=True)
    bad = torch.tensor([[0.0, 3.0, 0.0]], requires_grad=True)
    args = dict(
        legal_mask=mask,
        chosen=torch.tensor([0]),
        alternative=torch.tensor([1]),
        preference=torch.tensor([1.0]),
        anchor_logits=anchor,
        anchor_beta=0.0,
    )
    good_loss, _ = paired_preference_loss(good, **args)
    bad_loss, _ = paired_preference_loss(bad, **args)
    assert good_loss < bad_loss
    good_loss.backward()
    assert good.grad[0, 0] < 0 and good.grad[0, 1] > 0


def test_preference_loss_rejects_illegal_action():
    with pytest.raises(ValueError, match='not legal'):
        paired_preference_loss(
            torch.zeros(1, 2),
            torch.tensor([[True, False]]),
            torch.tensor([0]),
            torch.tensor([1]),
            torch.tensor([1.0]),
            torch.zeros(1, 2),
        )


def test_preference_loss_accepts_nonnegative_sample_weights():
    loss, metrics = paired_preference_loss(
        torch.tensor([[2.0, 0.0]]),
        torch.tensor([[True, True]]),
        torch.tensor([0]),
        torch.tensor([1]),
        torch.tensor([1.0]),
        torch.zeros(1, 2),
        sample_weight=torch.tensor([0.5]),
        anchor_beta=0.0,
    )
    assert torch.isfinite(loss) and metrics['preference_loss'] > 0


def test_pair_aggregation_weights_ties_and_discordance_over_all_repeats():
    row = aggregate_pair(
        {
            'rollouts': 4,
            'ties': 3,
            'total_steps': 40,
            'pairs': [{'chosen_outcome': 1, 'alternative_outcome': -1}],
        },
        {'legal_mask': []},
        2,
        3,
        'ordinary',
        1,
    )
    assert row['mean_difference'] == 0.5
    assert row['sample_weight'] == 0.5
    assert row['pair_repeats'] == 4 and row['ties'] == 3
    assert row['continuation_steps'] == 40


def test_default_decision_filter_excludes_reroll_roots_and_all_keeps_both():
    assert should_collect_root('ordinary', 'ordinary')
    assert not should_collect_root('ordinary', 'reroll')
    assert not should_collect_root('reroll', 'ordinary')
    assert should_collect_root('reroll', 'reroll')
    assert should_collect_root('all', 'ordinary')
    assert should_collect_root('all', 'reroll')
