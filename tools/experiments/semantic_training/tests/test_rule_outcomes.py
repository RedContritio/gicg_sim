from dataclasses import replace

import pytest

from tools.experiments.semantic_training.rule_outcomes import capture, FIELDS
from tools.experiments.semantic_training.rule_probe import case, variant
from tools.experiments.semantic_training.teams import with_teams
from tools.rule_validation.outcomes import seek
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory


@pytest.mark.parametrize('name', ['凯亚', '迪卢克', '芭芭拉', '砂糖', '菲谢尔'])
def test_five_character_labels_restore_state(name):
    cfg = load_cfg('configs/dmc/native_starter.toml')
    others = [n for n in cfg.scenario.char_pool if n != name]
    cfg = with_teams(cfg, [name] + others[:2], others[:3])
    cfg = replace(cfg, scenario=replace(cfg.scenario, fix_dice=[0] * 7 + [8]))
    env = make_env_factory(cfg, None, 94530)(0, layout_seed=7)
    try:
        groups = seek(env, [('Skill',)], player=0)
        before = env.export_view()
        identities = env.get_action_identities().copy()
        actions = groups[0]
        row = capture(env, actions)
        assert row['fields'] == FIELDS
        assert all(len(t) == len(FIELDS) for t in row['targets'])
        assert any(t[1] < 0 for t in row['targets'])
        assert env.export_view() == before
        assert (env.get_action_identities() == identities).all()
        # Measuring alternatives must not contaminate the actual next transition.
        action = actions[0]
        env.step(action)
        enemy_loss = sum(c['hp'] for c in env.export_view()['players'][1]['chars']) - sum(
            c['hp'] for c in before['players'][1]['chars']
        )
        assert enemy_loss == row['targets'][0][1]
    finally:
        env.close()


def test_swapping_rule_values_swaps_measured_targets(tmp_path):
    outcomes = []
    for index, damages in enumerate(((2, 6), (6, 2))):
        data = tmp_path / str(index)
        variant('data', data, damages)
        env, groups = case(data, 94531, 7)
        try:
            row = capture(env, [g[0] for g in groups])
            outcomes.append([t[1] for t in row['targets']])
        finally:
            env.close()
    assert outcomes == [[-2, -6], [-6, -2]]
