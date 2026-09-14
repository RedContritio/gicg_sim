"""Immutable opponents with reproducible prioritized fictitious self-play sampling."""

import copy
import math
import random


def pfsp(scores, floor=0.05):
    if not scores or not 0 < floor <= 1:
        raise ValueError('nonempty scores and positive sampling floor required')
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in scores):
        raise ValueError('scores must be finite probabilities')
    weights = [max(floor, (1 - p) ** 2) for p in scores]
    return [w / sum(weights) for w in weights]


class LeaguePool:
    """Checkpoint the draw stream and exact opponent distribution, not live weights."""

    def __init__(self, entries, builders, seed, identity):
        if not entries or len({e['id'] for e in entries}) != len(entries):
            raise ValueError('opponent IDs must be nonempty and unique')
        if any(not math.isfinite(e['weight']) or e['weight'] <= 0 for e in entries):
            raise ValueError('weights must be positive and finite')
        if set(builders) != {e['id'] for e in entries}:
            raise ValueError('builders must exactly match entries')
        self.entries = copy.deepcopy(entries)
        self.builders = builders
        self.identity = identity
        self.rng = random.Random(seed)
        self.draws = {e['id']: 0 for e in entries}

    def sample(self):
        entry = self.rng.choices(self.entries, weights=[e['weight'] for e in self.entries], k=1)[0]
        seed = self.rng.randrange(2**31)
        player = self.builders[entry['id']](seed)
        self.draws[entry['id']] += 1
        return player

    def state_dict(self):
        return {
            'schema': 1,
            'identity': self.identity,
            'entries': copy.deepcopy(self.entries),
            'rng': self.rng.getstate(),
            'draws': dict(self.draws),
        }

    def load_state_dict(self, saved):
        if (
            saved.get('schema') != 1
            or saved.get('identity') != self.identity
            or saved.get('entries') != self.entries
            or set(saved.get('draws', {})) != set(self.draws)
        ):
            raise ValueError('league schedule changed: create a new experiment instead of silent resume')
        self.rng.setstate(saved['rng'])
        self.draws = dict(saved['draws'])
