"""need_target (pending target / forced-switch continuation) regression tests.

Production smoke (configs/az/exit_smoke.toml, native 3v3 pool) died with
``selfplay: env.step returned need_target`` — need_target is a NORMAL
mid-game state (gicg_env/env.py step docstring): the played action left
a pending target / forced-switch continuation, and the NEXT step call
(from the then-acting target chooser) resolves it. The semantic
pipelines (tools/experiments/semantic_training/rl_rollout.py,
evaluate.py) never special-case it; the AZ play stack now matches.

These tests use the native_latest pool where 砂糖's skill
(风灵作成_陆参零捌: force_switch_previous(Player.Enemy)) and the
鹤归之时 card (force_switch_next) trigger continuations for real —
verified non-vacuous: the pre-fix selfplay raises on the same seeded
scenario, and every game here records >0 real (non-simulated)
need_target events.

The sim-depth tracker distinguishes REAL play steps (the selfplay loop)
from MCTS tree descent / greedy scoring steps, which step the same env
via snapshot/restore. This makes the counter_target invariant exact:

    rows_without_counter == (# real need_target events that followed a
                             recorded decision) + (1 if the game ended
                             on a recorded decision)

A recorded decision whose env.step returned need_target must keep
has_counter_target=False: the after-state is a pending-target
intermediate, not the resolved decision state.
"""

from __future__ import annotations

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.core.matchup.greedy_player import GreedyPlayer
from training.paradigms.az.buffer import STEP_DYNAMIC_KEYS
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.network import Agent, AgentConfig
import training.paradigms.az.selfplay as sp
from training.paradigms.az.selfplay import play_self_game, play_vs_opponent_game

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16

# 砂糖's skill forces the ENEMY to switch (target chooser = opponent);
# 鹤归之时 forces the actor's next switch. Both suspend for input →
# STEP_NEED_TARGET. Teams/decks mirror the production smoke scenario.
TEAM_0 = ['砂糖', '菲谢尔', '芭芭拉']
TEAM_1 = ['凯亚', '迪卢克', '芭芭拉']
_CARDS = [
    '一掷乾坤',
    '交给我吧！',
    '光辉的季节',
    '兽肉薄荷卷',
    '星天之兆',
    '北地烟熏鸡',
    '换班时间',
    '最好的伙伴！',
    '本大爷还没有输！',
    '派蒙',
    '烤蘑菇披萨',
    '运筹帷幄',
    '莲花酥',
    '甜甜花酿鸡',
    '白垩之术',
]
DECK = _CARDS + [
    '鹤归之时',
    '鹤归之时',
    '甜甜花酿鸡',
    '白垩之术',
    '莲花酥',
    '蒙德土豆饼',
    '运筹帷幄',
    '送你一程',
    '鸣神大社',
    '北地烟熏鸡',
    '交给我吧！',
    '烤蘑菇披萨',
    '星天之兆',
    '兽肉薄荷卷',
    '一掷乾坤',
]

EXPECTED_STEP_KEYS = set(STEP_DYNAMIC_KEYS) | {'buffs'}


class _TrackingEnv(GicgEnv):
    """Records every env.step outcome with a sim-depth flag (>0 while
    inside MCTS search / opponent scoring, which step the same env via
    snapshot/restore)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.step_log = []
        self.sim_depth = 0

    def step(self, action_idx):
        acting = self.acting_player
        phase = self.phase
        out = super().step(action_idx)
        self.step_log.append((acting, bool(out[3].get('need_target', False)), bool(out[2]), phase, self.sim_depth))
        return out


def _make_env(seed: int) -> _TrackingEnv:
    env = _TrackingEnv(
        TEAM_0,
        TEAM_1,
        seed=seed,
        data_dir=DATA_DIR,
        pool='native_latest',
        max_rounds=10,
        decks=[DECK, DECK],
    )
    env.reset(seed=seed)
    return env


def _make_agent() -> Agent:
    torch.manual_seed(0)
    np.random.seed(0)
    return Agent(
        AgentConfig(
            n_counter_slots=N_COUNTER_SLOTS,
            n_hooks=900,
            max_ops_per_hook=128,
            max_actions=2048,
            d_model=8,
            n_cross_layers=1,
            dropout=0.0,
        )
    )


def _pool_refs(env: GicgEnv) -> list[int]:
    view = env.export_view()
    hand = view['players'][0]['hand']
    filler = hand[0]['ref']
    return [c['ref'] for c in hand] + [filler] * view['players'][0]['deck_count']


def _mcts_cfg() -> MCTSConfig:
    return MCTSConfig(n_rollouts=1, profile=False, temperature_switch_step=999)


@pytest.fixture
def sim_tracker(monkeypatch):
    """Marks env.sim_depth around agent MCTS decisions and greedy
    opponent selects so the test can tell real play steps from
    simulation steps on the shared env object."""

    def install(env):
        def wrap(fn):
            def inner(*a, **k):
                env.sim_depth += 1
                try:
                    return fn(*a, **k)
                finally:
                    env.sim_depth -= 1

            return inner

        monkeypatch.setattr(sp, '_mcts_decide', wrap(sp._mcts_decide))
        monkeypatch.setattr(GreedyPlayer, 'select_action', wrap(GreedyPlayer.select_action))

    return install


def _check_invariant(tag, env, result, agent_player):
    """Exact counter_target ↔ need_target correlation (see module docstring)."""
    real = [x for x in env.step_log if x[4] == 0]
    real_nt = [x for x in real if x[1]]
    assert real_nt, f'{tag}: game never hit need_target — test is vacuous'
    sim_nt = [x for x in env.step_log if x[1] and x[4] > 0]
    assert sim_nt, f'{tag}: MCTS simulation never hit need_target — tree-descend fix untested'
    # Real need_target events following a RECORDED decision (phase-1
    # selection steps are never recorded).
    rec_nt = [x for x in real_nt if x[3] != 1 and (agent_player is None or x[0] == agent_player)]
    final_flag = int(bool(env.step_log[-1][2]) and (agent_player is None or env.step_log[-1][0] == agent_player))
    rows_wo_counter = [s for s in result.steps if not s['has_counter_target']]
    assert len(rows_wo_counter) == len(rec_nt) + final_flag, (
        f'{tag}: rows without counter_target ({len(rows_wo_counter)}) != '
        f'recorded need_target skips ({len(rec_nt)}) + terminal row ({final_flag})'
    )
    for step in result.steps:
        assert set(step.keys()) == EXPECTED_STEP_KEYS
    return len(real_nt), len(rec_nt)


def test_fixed_opponent_game_survives_need_target(sim_tracker):
    """Agent (seat 0, 砂糖) vs F1-D1 greedy: need_target steps continue
    the game; recorded need_target steps keep has_counter_target=False."""
    env = _make_env(seed=1)
    try:
        agent = _make_agent()
        sim_tracker(env)
        result = play_vs_opponent_game(
            agent,
            env,
            SharedFixedPool(_pool_refs(env)),
            random.Random(0),
            _mcts_cfg(),
            GreedyPlayer(features='F1', depth=1, dice_greedy=True, seed=1),
            max_game_steps=512,
            n_counter_slots=N_COUNTER_SLOTS,
            max_actions=2048,
        )
        assert result.n_steps > 0
        assert result.winner in (0, 1, 2)
        n_real_nt, n_rec_nt = _check_invariant('vs', env, result, agent_player=0)
        assert n_rec_nt >= 1, (
            f'no RECORDED agent decision hit need_target (real={n_real_nt}) — '
            'counter_target skip on recorded rows untested'
        )
    finally:
        env.close()


def test_mirror_game_survives_need_target(sim_tracker):
    """Mirror path: same continuation handling on both seats."""
    env = _make_env(seed=1)
    try:
        agent = _make_agent()
        sim_tracker(env)
        result = play_self_game(
            agent,
            env,
            SharedFixedPool(_pool_refs(env)),
            random.Random(0),
            _mcts_cfg(),
            max_game_steps=512,
            n_counter_slots=N_COUNTER_SLOTS,
            max_actions=2048,
        )
        assert result.n_steps > 0
        assert result.winner in (0, 1, 2)
        _check_invariant('mirror', env, result, agent_player=None)
    finally:
        env.close()
