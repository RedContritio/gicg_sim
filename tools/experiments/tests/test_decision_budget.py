import pytest

from gicg_env import ACTION_CARD, ACTION_END_TURN, ACTION_REROLL
from gicg_env import GicgEnv, PHASE_SELECT_ACTIVE
from tools.experiments.semantic_training.decision_budget import DecisionBudget


class SequenceEnv:
    def __init__(self, kinds):
        self.kinds = kinds
        self.position = 0

    @property
    def done(self):
        return self.position == len(self.kinds)

    def get_legal_actions(self):
        return [self.kinds[self.position]], [0]

    def step(self):
        self.position += 1


def test_last_budgeted_card_completes_internal_choices():
    env = SequenceEnv([ACTION_CARD] + [ACTION_REROLL] * 18 + [ACTION_END_TURN])
    budget = DecisionBudget(1)
    for _ in budget.iterate(env):
        env.step()
    assert env.position == 19 and not env.done
    assert (budget.actions, budget.decisions, budget.internal) == (1, 19, 18)


def test_terminal_after_internal_choices_and_legacy_budget():
    for kinds, limit, expected in [
        ([ACTION_CARD, ACTION_REROLL], 1, 2),
        ([ACTION_CARD, ACTION_END_TURN], 1, 1),
        ([ACTION_CARD, ACTION_END_TURN], 2, 2),
    ]:
        env = SequenceEnv(kinds)
        budget = DecisionBudget(limit)
        for _ in budget.iterate(env):
            env.step()
        assert env.position == expected


def test_internal_stall_fails_instead_of_hanging():
    env = SequenceEnv([ACTION_REROLL])
    with pytest.raises(RuntimeError, match='internal decision budget exhausted'):
        for _ in DecisionBudget(1, max_internal_per_action=3).iterate(env):
            pass


def test_real_native_card_finishes_both_rerolls_at_last_action_budget():
    team = ['凯亚', '迪卢克', '芭芭拉']
    env = GicgEnv(team, team, pool='native_latest', decks=[['一掷乾坤'], ['甜甜花酿鸡']])
    try:
        env.reset(seed=41)
        while env.phase == PHASE_SELECT_ACTIVE:
            env.step(0)
        env.set_player_dice(0, [2, 0, 0, 0, 0, 0, 0, 1])
        budget = DecisionBudget(1)
        for _ in budget.iterate(env):
            kinds, _ = env.get_legal_actions()
            if kinds[0] == ACTION_REROLL:
                env.step(0)  # keep every die, confirming both rounds
            else:
                card = next(
                    i
                    for i, (kind, name, _) in enumerate(env.get_action_labels())
                    if kind == 'Card' and name == '一掷乾坤'
                )
                env.step(card)
        assert (budget.actions, budget.internal, budget.decisions) == (1, 6, 7)
        assert env.get_legal_actions()[0][0] != ACTION_REROLL
        assert env.acting_player == 0 and len(env.hand_refs(0)) == 0
    finally:
        env.close()
