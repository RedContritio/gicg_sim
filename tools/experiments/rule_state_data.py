"""Engine labels for discount triggers and food target eligibility; legal-play setup."""

import numpy as np

from gicg_env import GicgEnv
from tools.experiments.tactical_data import step_checked
from training.paradigms.dmc._episode import capture_obs


def collect(agent, seeds):
    rows = []
    for seed in seeds:
        for side in (0, 1):
            for fed in (-1, 0, 1):
                env = GicgEnv(
                    ['赤蝶', '墨客'],
                    ['赤蝶', '墨客'],
                    seed=seed,
                    card_pool=['乘胜追击', '美味烧鸡', '美味烧鸡'],
                    decks=[['乘胜追击', '美味烧鸡', '美味烧鸡']] * 2,
                    pool=['v_legacy', 'test_basic'],
                    data_dir='data',
                    fix_dice=[0, 0, 0, 0, 0, 0, 0, 12],
                    obs_mask=['enemy_dice'],
                )
                trace = []

                def act(kind, name=None, target=None):
                    labels = env.get_action_labels()
                    ids = env.get_action_identities()
                    index = next(
                        i
                        for i, lab in enumerate(labels)
                        if lab[0] == kind
                        and (name is None or lab[1] == name)
                        and (target is None or ids[i, 4] == target)
                    )
                    trace.append(index)
                    step_checked(env, index)

                try:
                    env.reset(seed=seed)
                    env.log_suspend()
                    if side == 1:
                        act('EndTurn')
                    if fed >= 0:
                        act('Card', '美味烧鸡', fed)
                    act('Card', '乘胜追击')
                    agent.game_start(env.static_obs)
                    for count in range(5):
                        assert env.acting_player == side
                        labels = env.get_action_labels()
                        ids = env.get_action_identities()
                        payments = env.get_legal_action_payments()
                        skill = next(i for i, lab in enumerate(labels) if lab[0] == 'Skill')
                        cost = int(payments[skill].sum())
                        eligible = {int(ids[i, 4]) for i, lab in enumerate(labels) if lab[:2] == ('Card', '美味烧鸡')}
                        y = np.array([cost == 0, 0 in eligible, 1 in eligible], dtype=np.float32)
                        np.testing.assert_array_equal(y, [count == 3, fed != 0, fed != 1])
                        assert cost in (0, 3)
                        obs = capture_obs(env, agent)
                        # The auxiliary head reads state only. Do not expose the oracle's
                        # candidate costs or legal target set via the dummy Q-head call.
                        obs['action_refs'] = np.array([[3, -1, -1]], dtype=np.int64)
                        obs['action_payments'] = np.zeros((1, 8), dtype=np.float32)
                        obs['legal_mask'] = np.ones(1, dtype=bool)
                        obs['n_legal'] = 1
                        rows.append(
                            dict(
                                obs=obs,
                                utility=np.zeros(1),
                                labels=y,
                                cost=cost,
                                seed=seed,
                                side=side,
                                fed=fed,
                                count=count,
                                trace=list(trace),
                            )
                        )
                        if count < 4:
                            act('Switch')
                            if env.acting_player != side:
                                act('EndTurn')
                finally:
                    env.close()
        print('RULE STATES', seed, flush=True)
    return rows
