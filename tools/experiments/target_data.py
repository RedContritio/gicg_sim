"""Balanced legal-play fixtures for joint healing-card target decisions."""

import numpy as np

from gicg_env import GicgEnv
from tools.experiments.tactical_data import label_actions, step_checked
from training.paradigms.dmc._episode import capture_obs

ENV = dict(
    team_0=['赤蝶', '墨客'],
    team_1=['赤蝶', '墨客'],
    card_pool=['美味烧鸡'],
    pool=['v_legacy', 'test_basic'],
    data_dir='data',
    max_rounds=8,
    fix_dice=[0, 0, 0, 0, 0, 0, 0, 12],
    obs_mask=['enemy_dice'],
)


def setup(seed, side, wounded, active):
    # GicgEnv takes the two teams positionally; preserve a serializable config.
    kwargs = dict(ENV)
    env = GicgEnv(kwargs.pop('team_0'), kwargs.pop('team_1'), seed=seed, **kwargs)
    trace = []

    def act(kind, slot=None):
        labels = env.get_action_labels()
        index = next(i for i, label in enumerate(labels) if label[0] == kind and (slot is None or label[2] == slot))
        trace.append({'index': index, 'label': labels[index], 'actor': env.acting_player})
        step_checked(env, index)

    try:
        env.reset(seed=seed)
        env.log_suspend()
        if side == 1:
            act('Switch', 1)  # hand action to P1 without inflicting damage
        if wounded == 1:
            act('Switch', 1)
        else:
            act('Skill')
        act('Skill')  # opponent damages the requested character
        if active != wounded:
            act('Switch', active)
            act('EndTurn')  # opponent gives control back without another hit
        assert env.acting_player == side
        chars = env.export_view()['players'][side]['chars']
        assert chars[wounded]['hp'] < chars[wounded]['hp_max']
        assert chars[1 - wounded]['hp'] == chars[1 - wounded]['hp_max']
        assert env.export_view()['players'][side]['active_char'] == active
        return env, trace
    except BaseException:
        env.close()
        raise


def collect(agent, seeds):
    rows = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        for side in (0, 1):
            for wounded in (0, 1):
                for active in (0, 1):
                    env, trace = setup(seed, side, wounded, active)
                    try:
                        env.get_legal_actions()
                        agent.game_start(env.static_obs)
                        obs = capture_obs(env, agent)
                        identities = env.get_action_identities()
                        candidates = np.flatnonzero(identities[:, 0] == 1)
                        if len(candidates) != 2:
                            raise AssertionError('expected exactly two healing target actions')
                        rng.shuffle(candidates)
                        values = label_actions(env)[candidates]
                        if set(values) != {0, 1}:
                            raise AssertionError(f'healing target labels are not conditional: {values}')
                        targets = obs['action_refs'][candidates, 2]
                        np.testing.assert_array_equal(values == 1, targets == wounded)
                        np.testing.assert_array_equal(
                            obs['action_payments'][candidates[0]], obs['action_payments'][candidates[1]]
                        )
                        for key in ('action_refs', 'action_payments', 'legal_mask'):
                            obs[key] = obs[key][candidates].copy()
                        obs['n_legal'] = 2
                        rows.append(
                            dict(
                                obs=obs,
                                utility=values,
                                seed=seed,
                                side=side,
                                wounded=wounded,
                                active=active,
                                trace=trace,
                                original_indices=candidates.tolist(),
                            )
                        )
                    finally:
                        env.close()
        print('TARGET COLLECT', seed, flush=True)
    return rows
