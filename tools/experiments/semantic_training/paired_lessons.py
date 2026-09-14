"""Matched-state engine consequences across five-character numeric interventions."""

from dataclasses import replace
from pathlib import Path
import random
import re
import tempfile

import numpy as np
import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.rule_outcomes import FIELDS, target
from tools.experiments.semantic_training.teams import with_teams
from tools.rule_validation.outcomes import seek
from tools.rule_validation.patches import Patch, apply
from tools.rule_validation.variants import specification
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.network import AgentConfig


SKILL_NAMES = {
    '演唱开始': '演唱，开始♪',
    '陆参零捌': '风灵作成·陆参零捌',
    '柒伍同构贰型': '禁·风灵作成·柒伍同构贰型',
}
TRAIN_VALUES = ((1, 5), (3, 7))
HELDOUT_VALUES = ((2, 6), (4, 8))


def tasks(config, catalog, shape, seed, contexts=6):
    spec, _ = specification(catalog)
    result = []
    for split, pairs, count, offset in (
        ('train', TRAIN_VALUES, contexts, 0),
        ('states', TRAIN_VALUES, max(1, contexts // 2), 10000),
        ('values', HELDOUT_VALUES, max(1, contexts // 2), 20000),
    ):
        for parameter in spec['parameters']:
            if parameter['kind'] not in ('damage', 'heal'):
                continue
            for index, values in enumerate(pairs):
                for context in range(count):
                    result.append(
                        dict(
                            config=config,
                            shape=shape,
                            parameter=parameter,
                            split=split,
                            values=values,
                            seed=seed + offset + context,
                            layout=seed + offset + context + 100,
                            hp=(3, 7, 10)[context % 3],
                            pair_index=index,
                        )
                    )
    return result


def setup_patches(source, characters, hp):
    """Identical synthetic starting HP/full energy in both halves, visible in observations."""
    patches = []
    for name in characters:
        path = f'pools/native_latest/characters/{name}/{name}.lua'
        text = (Path(source) / path).read_text(encoding='utf-8')
        hp_match = re.search(r'declare_counter\("hp",\s*Scope.Self,\s*10,', text)
        energy = re.search(r'declare_counter\("energy",\s*Scope.Self,\s*0,\s*\{ max = (\d+)', text)
        if not hp_match or not energy:
            raise ValueError(f'unsupported diagnostic initial counters: {name}')
        patches.append(Patch(path, hp_match[0], re.sub(r'10,$', f'{hp},', hp_match[0])))
        patches.append(Patch(path, energy[0], re.sub(r'0,', f'{energy[1]},', energy[0], count=1)))
    return patches


def build_pair(task):
    torch.set_num_threads(1)
    cfg = load_cfg(task['config'])
    p = task['parameter']
    rng = random.Random(task['seed'])
    pool = cfg.scenario.char_pool
    team = [p['character']] + rng.sample([c for c in pool if c != p['character']], 2)
    cfg = with_teams(cfg, team, rng.sample(pool, 3))
    skill = p['id'].rsplit('.', 1)[0]
    skill = SKILL_NAMES.get(skill, skill)
    observer = SemanticAgent(AgentConfig(**task['shape']))
    rows = []
    with tempfile.TemporaryDirectory(prefix='gicg-paired-') as temp:
        for index, value in enumerate(task['values']):
            data = Path(temp) / str(index)
            after = p['template'].replace('VALUE', str(value)).replace('BONUS', str(value + 2))
            patches = setup_patches(cfg.scenario.data_dir, pool, task['hp'])
            patches.append(Patch(p['path'], p['before'], after))
            manifest = apply(cfg.scenario.data_dir, data, patches)
            variant = replace(cfg, scenario=replace(cfg.scenario, data_dir=str(data), fix_dice=[0] * 7 + [8]))
            env = make_env_factory(variant, None, task['seed'])(0, layout_seed=task['layout'])
            try:
                group = seek(env, [('Skill', skill)], player=0)[0]
                observer.game_start(env.static_obs)
                obs = observer.observation(env)
                before = env.export_view()
                label = target(env, group[0])
                if env.export_view() != before:
                    raise AssertionError('oracle altered pre-action state')
                rows.append(dict(obs=obs, action=group[0], target=label, data_sha256=manifest['data_sha256']))
            finally:
                env.close()
    # The intervention is in rule IR; no dynamic-state, hand, payment or action-index shortcut.
    if rows[0]['obs'].keys() != rows[1]['obs'].keys():
        raise AssertionError('counterfactual observation schema changed')
    for key in rows[0]['obs'].keys() - {'hook_ir'}:
        if not np.array_equal(rows[0]['obs'][key], rows[1]['obs'][key]):
            raise AssertionError(f'unmatched pair: {p["id"]}/{key}')
    if rows[0]['action'] != rows[1]['action']:
        raise AssertionError('counterfactual action identity changed')
    if np.array_equal(rows[0]['obs']['hook_ir'], rows[1]['obs']['hook_ir']):
        raise AssertionError('numeric intervention is invisible in rule IR')
    return dict(
        split=task['split'],
        parameter=p['id'],
        character=p['character'],
        kind=p['kind'],
        values=task['values'],
        hp=task['hp'],
        seed=task['seed'],
        layout=task['layout'],
        field=FIELDS.index('own_hp_delta' if p['kind'] == 'heal' else 'enemy_hp_delta'),
        rows=rows,
    )
