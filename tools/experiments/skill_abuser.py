"""Evaluation-only skill-first policy using original engine declarations."""

import json
import os
import tempfile
from pathlib import Path
import subprocess

from training.core.matchup.greedy_dice import filter_logical_actions

ELEMENTS = ('fire', 'ice', 'water', 'electro', 'geo', 'anemo', 'dendro')
NAME = '技能滥用者'


def load_skill_catalog(cfg):
    scenario = cfg.scenario
    pools = scenario.pool
    if isinstance(pools, str):
        pools = [pools]
    payload = {
        'data_dir': scenario.data_dir,
        'pools': pools,
        'players': [{'chars': [{'name': name} for name in team]} for team in (scenario.team_0, scenario.team_1)],
        'card_pool': scenario.card_pool,
        'seed': 0,
    }
    result = subprocess.run(
        ['go', 'run', './tools/cards/skill_catalog'],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            'GOCACHE': os.environ.get('GOCACHE', str(Path(tempfile.gettempdir()) / 'gicg-eval-go-cache')),
        },
    )
    return {(skill['CharName'], skill['Name']): skill for skill in json.loads(result.stdout)}


def cost_rank(cost, element):
    """Descending lexicographic rank; off-element > own-element > unspecified."""
    dice = cost['Dices']
    specific = dice['Specific']
    own = ELEMENTS.index(element) if element in ELEMENTS else -1
    off_element = any(count > 0 and color != own for color, count in enumerate(specific))
    tier = 2 if off_element else 1 if sum(specific) else 0
    return (cost['Energy'], tier, sum(specific), dice['Match'], dice['Any'])


class SkillAbuser:
    def __init__(self, catalog):
        self.catalog = catalog
        self.game_start(None)

    def game_start(self, static_obs):
        self._round = None
        self._used = {}

    def select_action(self, env):
        kinds, _ = env.get_legal_actions()
        if not len(kinds):
            raise ValueError('skill abuser called without legal actions')
        if env.has_pending:
            return 0  # Required target/forced-switch choice, never a voluntary action.
        candidates = [i for i, kind in enumerate(kinds) if kind == 0]
        if candidates:
            state = env.export_view()
            if state['round'] != self._round:
                self._round = state['round']
                self._used.clear()
            view = state['players'][env.acting_player]
            character = view['chars'][view['active_char']]
            labels = env.get_action_labels()
            preferred_payments = set(filter_logical_actions(env))
            candidates = [i for i in candidates if i in preferred_payments]

            def skill_key(index):
                skill = self.catalog[(character['name'], labels[index][1])]
                return (env.acting_player, view['active_char'], skill['ID'])

            candidates = [i for i in candidates if self._used.get(skill_key(i), 0) < 2]

            def rank(index):
                skill = self.catalog[(character['name'], labels[index][1])]
                return (*cost_rank(skill['Cost'], character['element']), -skill['ID'])

            if candidates:
                chosen = max(candidates, key=rank)
                key = skill_key(chosen)
                self._used[key] = self._used.get(key, 0) + 1
                return chosen
        endings = [i for i, kind in enumerate(kinds) if kind == 3]
        if endings:
            return endings[0]
        if all(kind == 2 for kind in kinds):
            return 0  # Initial active-character selection.
        raise ValueError('no legal skill/end/mandatory choice; unsupported decision phase')
