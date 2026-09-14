"""Real engine variants, disjoint values, source isolation and full-game labels."""

from pathlib import Path

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from tools.rule_validation.variants import specification, sample, environment_config
from tools.rule_validation.patches import Patch, apply, digest_tree
from tools.rule_validation.outcomes import seek, measure
from training.core.config.loader import load_cfg
from tools.experiments.semantic_training.data import teacher_episode

CATALOG = 'configs/rule_validation/native_variants.toml'
SPEC, _ = specification(CATALOG)


def test_catalog_confined_reproducible_and_heldout():
    chars = {p['character'] for p in SPEC['parameters']}
    assert len(chars) == 5 and len(SPEC['parameters']) == 30
    for seed in range(30):
        a = sample(SPEC, seed, chars)
        assert a == sample(SPEC, seed, chars)
        assert 1 <= len(a[0]) <= 2
        for split in ('train', 'heldout'):
            _, changes = sample(SPEC, seed, chars, split)
            for change in changes:
                p = next(p for p in SPEC['parameters'] if p['id'] == change['id'])
                assert change['after'] in p[split] and change['after'] != p['base']
    cfg = load_cfg('configs/dmc/native_starter.toml')
    flags = []
    for index in range(4):
        with environment_config(cfg, CATALOG, 100 + index, index) as (changed, manifest):
            flags.append(manifest['variant'])
            if manifest['variant']:
                assert Path(changed.scenario.data_dir).exists()
                temp = changed.scenario.data_dir
        if flags[-1]:
            assert not Path(temp).exists()
    assert flags == [False, True, True, False]


@pytest.mark.parametrize('parameter', SPEC['parameters'], ids=lambda p: p['id'])
def test_every_declared_parameter_loads_into_engine(parameter, tmp_path):
    value = next(v for v in parameter['train'] if v != parameter['base'])
    after = parameter['template'].replace('VALUE', str(value)).replace('BONUS', str(value + 2))
    apply('data', tmp_path / 'data', [Patch(parameter['path'], parameter['before'], after)])
    name = parameter['character']
    with GicgEnv([name], [name], pool='native_latest', data_dir=str(tmp_path / 'data'), card_pool=[]) as env:
        env.reset(seed=10)
        assert env.get_rule_graph()['version'] == 2


@pytest.mark.parametrize(
    'name,skill',
    [
        ('凯亚', '仪典剑术'),
        ('迪卢克', '淬炼之剑'),
        ('芭芭拉', '水之浅唱'),
        ('砂糖', '简式风灵作成'),
        ('菲谢尔', '罪灭之矢'),
    ],
)
def test_damage_and_payment_variants_are_executed_and_observable(name, skill, tmp_path):
    damage = next(p for p in SPEC['parameters'] if p['id'] == skill + '.damage')
    cost = next(p for p in SPEC['parameters'] if p['id'] == skill + '.cost')
    observations, payments = [], []
    for index, value in enumerate((2, 5)):
        destination = tmp_path / str(index)
        apply(
            'data',
            destination,
            [Patch(p['path'], p['before'], p['template'].replace('VALUE', str(value))) for p in (damage, cost)],
        )
        with GicgEnv(
            [name],
            [name],
            pool='native_latest',
            data_dir=str(destination),
            card_pool=[],
            fix_dice=[0] * 7 + [8],
            seed=7,
        ) as env:
            env.reset(seed=10)
            indices = seek(env, [('Skill', skill)], player=0)[0]
            assert measure(env, indices[0])['hp_loss'][1] == value
            payments.append(np.asarray(env.get_legal_action_payments())[indices[0]].copy())
            observations.append(env.static_obs.copy())
    assert not np.array_equal(observations[0], observations[1])
    assert not np.array_equal(payments[0], payments[1])


def test_teacher_uses_variant_for_full_game_and_keeps_manifest(tmp_path):
    torch.set_num_threads(1)
    before = digest_tree('data/pools/native_latest')
    result = teacher_episode(('configs/dmc/native_starter.toml', 1, str(tmp_path), 93900, CATALOG))
    saved = torch.load(result['path'], weights_only=False)
    assert result['rule_variant']['variant'] and saved['rule_variant'] == result['rule_variant']
    assert saved['winner'] in (0, 1) and saved['rows']
    assert sum(result['deck_counts'].values()) == 60
    assert digest_tree('data/pools/native_latest') == before
