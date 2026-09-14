"""Versioned evaluation opponents; does not change the training opponent pool."""

import hashlib
from pathlib import Path
import random

from tools.experiments.skill_abuser import NAME as SKILL_ABUSER, SkillAbuser
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.paradigms.dmc._opponent import RandomPlayer

VERSION = 'eval-ladder-v17-skill-cap2'
MIXED = 'F1-D1-50%'
BASELINES = ('random', MIXED, 'F1-D1', 'F1-D2', SKILL_ABUSER)


class MixedD1:
    """Per-decision 50% D1 / 50% uniform legal-action random; seeded separately."""

    def __init__(self, seed):
        self.rng = random.Random(derive_seed(seed, 'mix-branch'))
        self.random = RandomPlayer(derive_seed(seed, 'mix-random'))
        self.greedy = GreedyPlayer(features='F1', depth=1, dice_greedy=True, seed=derive_seed(seed, 'mix-greedy'))

    def select_action(self, env):
        player = self.greedy if self.rng.random() < 0.5 else self.random
        return player.select_action(env)


def make_baseline(name, seed, catalog):
    if name == 'random':
        return RandomPlayer(seed)
    if name == MIXED:
        return MixedD1(seed)
    if name in ('F1-D1', 'F1-D2'):
        return GreedyPlayer(features='F1', depth=int(name[-1]), dice_greedy=True, seed=seed)
    if name == SKILL_ABUSER:
        return SkillAbuser(catalog)
    raise ValueError(f'unknown evaluation baseline: {name}')


def evaluation_provenance():
    root = Path(__file__).resolve().parents[2]
    names = (
        'tools/experiments/eval_ladder.py',
        'tools/experiments/skill_abuser.py',
        'tools/experiments/evaluate_clean.py',
        'tools/cards/skill_catalog/main.go',
    )
    return {
        'version': VERSION,
        'sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
    }
