"""Rule links stay inside actual observation axes in a real current-pool game."""

import numpy as np
import pytest

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory


def test_rule_graph_real_environment_indices():
    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    factory = make_env_factory(cfg, None, 122000)
    for seed in (122001, 122002):
        env = factory(0, layout_seed=seed)
        try:
            graph = env.get_rule_graph()
            assert graph['version'] == 2
            assert graph['counter_links'] and graph['card_links']
            labels = env.get_active_counter_slot_labels()
            hooks = env.get_active_hook_labels()
            for slot, hook, binding, method in graph['counter_links']:
                assert 0 <= slot < len(labels) and labels[slot]
                assert 0 <= hook < len(hooks)
                assert binding >= -1 and method >= 0
            for slot, hook in graph['card_links']:
                assert 0 <= slot < 80 and 0 <= hook < len(hooks)
            assert graph['skill_links']
            for canonical, effect in graph['skill_links']:
                assert 0 <= canonical < len(hooks) and 0 <= effect < len(hooks)
            # Export itself must be a read-only schema query.
            before = env._get_obs().copy()
            assert graph == env.get_rule_graph()
            np.testing.assert_array_equal(before, env._get_obs())
        finally:
            env.close()


@pytest.mark.parametrize(
    'teams',
    [
        (['凯亚', '迪卢克', '芭芭拉'], ['凯亚', '砂糖', '菲谢尔']),
        (['砂糖', '菲谢尔', '芭芭拉'], ['砂糖', '菲谢尔', '芭芭拉']),
    ],
)
def test_all_native_skill_definitions_have_effect_references(teams):
    from gicg_env import GicgEnv

    with GicgEnv(*teams, pool='native_latest', data_dir='data', card_pool=[], seed=93810) as env:
        graph = env.get_rule_graph()
        from training.core.obs_constants import OBS_COUNTER_SLOTS, OBS_CHAR_SKILL_REFS_SIZE

        offset = OBS_COUNTER_SLOTS * 3
        refs = env.static_obs[offset : offset + OBS_CHAR_SKILL_REFS_SIZE]
        canonical = set(np.asarray(refs).reshape(-1)) - {-1}
        assert len(canonical) == 18
        linked = {source for source, effect in graph['skill_links'] if source != effect}
        assert canonical <= linked
