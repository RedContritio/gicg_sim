"""Count ordinary actions separately from a card's internal reroll decisions."""

from dataclasses import dataclass

from gicg_env import ACTION_REROLL


@dataclass
class DecisionBudget:
    max_actions: int
    max_internal_per_action: int = 256
    actions: int = 0
    decisions: int = 0
    internal: int = 0

    def iterate(self, env):
        if self.max_actions <= 0 or self.max_internal_per_action <= 0:
            raise ValueError('decision budget limits must be positive')
        consecutive = 0
        while not env.done:
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                if env.done:
                    break
                raise RuntimeError('nonterminal state has no legal decisions')
            reroll = kinds[0] == ACTION_REROLL
            if reroll:
                if not all(kind == ACTION_REROLL for kind in kinds):
                    raise RuntimeError('internal reroll mixed with ordinary actions')
                consecutive += 1
                if consecutive > self.max_internal_per_action:
                    raise RuntimeError('internal decision budget exhausted')
                self.internal += 1
            else:
                if self.actions >= self.max_actions:
                    break
                consecutive = 0
                self.actions += 1
            self.decisions += 1
            yield self.decisions - 1
