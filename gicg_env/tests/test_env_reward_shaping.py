"""Tests for GicgEnv.reward_shaping.

Covers:
- RewardShaping.from_arg: dict / instance / None / unknown-key raise
- reward_shaping=None → step() reward always 0.0
- Per-coef isolation: zeroing all-but-one coef only propagates that one term
- Terminal win/loss/draw bonuses wire the correct sign for the acting player
- Per-player attribution: damage dealt scores the dealer, damage taken scores
  the receiver — no cross-signal leakage
- reset() zeros the engine RewardAccum (and hence next step's delta)
"""

import os

import numpy as np
import pytest

from gicg_env import GicgEnv
from gicg_env.env import RewardShaping
from gicg_env.env_reward import compute_shaped_reward

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def make_env(team_0, team_1, reward_shaping=None, **kw):
    return GicgEnv(
        team_0,
        team_1,
        data_dir=DATA_DIR,
        reward_shaping=reward_shaping,
        **kw,
    )


def _drive_to_terminal(env, rng, max_steps=600):
    """Random self-play until done. Returns (total_reward_p0, last_info)."""
    total = 0.0
    info = None
    for _ in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        acting = env.acting_player
        a = int(rng.integers(0, len(kinds)))
        _, reward, _, info = env.step(a)
        if acting == 0:
            total += reward
    return total, info


class TestRewardShapingConfig:
    def test_from_arg_none_passthrough(self):
        assert RewardShaping.from_arg(None) is None

    def test_from_arg_instance_passthrough(self):
        rs = RewardShaping(hp_delta=1.0)
        assert RewardShaping.from_arg(rs) is rs

    def test_from_arg_dict(self):
        rs = RewardShaping.from_arg({'hp_delta': 1.0, 'terminal_win': 60.0})
        assert rs.hp_delta == 1.0
        assert rs.terminal_win == 60.0
        # unspecified coefs default to 0
        assert rs.hp_taken_penalty == 0.0
        assert rs.kill_bonus == 0.0

    def test_from_arg_rejects_unknown_key(self):
        """Misspelled coef names must raise — silently dropping means a
        configured coef trains on weight 0 with no warning."""
        with pytest.raises(ValueError, match='unknown keys'):
            RewardShaping.from_arg({'hp_delat': 1.0})  # typo

    def test_all_defaults_zero(self):
        """Default-constructed shaping = zero reward for any delta —
        explicit opt-in per term."""
        rs = RewardShaping()
        events_before = np.zeros(14, dtype=np.int32)
        events_after = np.array(
            [5, 3, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0],
            dtype=np.int32,
        )  # damage dealt, received, kills all nonzero
        r = compute_shaped_reward(rs, events_before, events_after, done=False, winner=-1, me=0)
        assert r == 0.0


class TestStepReturnShape:
    def test_step_returns_4_tuple(self):
        with make_env(['赤蝶'], ['赤蝶']) as env:
            ret = env.step(0)
            assert len(ret) == 4, 'step() must return (obs, reward, done, info)'
            obs, reward, done, info = ret
            assert obs is not None
            assert isinstance(reward, float)
            assert isinstance(done, bool) or done in (True, False)
            assert isinstance(info, dict)

    def test_shaping_none_gives_zero_reward(self):
        """AZ path: no shaping → every reward is exactly 0.0, including
        on terminal (terminal z is still in info['z'])."""
        rng = np.random.default_rng(42)
        with make_env(['赤蝶'], ['墨客'], reward_shaping=None) as env:
            for _ in range(200):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                a = int(rng.integers(0, len(kinds)))
                _, reward, _, _ = env.step(a)
                assert reward == 0.0


class TestTerminalBonus:
    def test_terminal_bonus_attributed_to_acting_player(self):
        """With only terminal_win/terminal_loss configured (all other
        coefs 0), the *terminal* step's reward must equal the signed
        bonus from the acting-at-terminal player's POV: +1 if that
        player won, -1 if they lost, 0 on draw. The non-acting player
        sees no terminal reward from env.step — its training-loop
        must handle terminal attribution for the opponent's trajectory
        externally (standard 2-player self-play pattern).
        """
        rs = {'terminal_win': 1.0, 'terminal_loss': 1.0}
        seen_at_least_one_terminal = False
        for seed in (0, 1, 7, 42, 100, 200):
            rng = np.random.default_rng(seed)
            with make_env(['赤蝶'], ['墨客'], reward_shaping=rs) as env:
                last_reward = None
                last_acting = None
                last_info = None
                for _ in range(600):
                    if env.done:
                        break
                    kinds, _ = env.get_legal_actions()
                    if len(kinds) == 0:
                        break
                    acting = env.acting_player
                    a = int(rng.integers(0, len(kinds)))
                    _, reward, done, info = env.step(a)
                    if done:
                        last_reward = reward
                        last_acting = acting
                        last_info = info
                        break
                if last_info is None:
                    continue
                seen_at_least_one_terminal = True
                winner = last_info['winner']
                if winner == 2:  # draw
                    assert last_reward == pytest.approx(0.0), f'seed={seed}: draw but terminal reward={last_reward}'
                elif winner == last_acting:
                    assert last_reward == pytest.approx(1.0), (
                        f'seed={seed}: terminal actor won, expected +1 got {last_reward}'
                    )
                else:
                    assert last_reward == pytest.approx(-1.0), (
                        f'seed={seed}: terminal actor lost, expected -1 got {last_reward}'
                    )
        assert seen_at_least_one_terminal, 'no seed terminated — test is vacuous'


class TestRewardAttribution:
    def test_damage_dealt_credits_dealer(self):
        """hp_delta=1 alone → dealer accumulates positive reward on their
        damage-dealing turns; receiver never gets positive reward from
        this coef (they only see damage_received, which this config
        zero-weights)."""
        rs = {'hp_delta': 1.0}
        rng = np.random.default_rng(3)
        with make_env(['赤蝶'], ['墨客'], reward_shaping=rs) as env:
            sum_p0 = 0.0
            sum_p1 = 0.0
            for _ in range(600):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                acting = env.acting_player
                a = int(rng.integers(0, len(kinds)))
                _, reward, _, _ = env.step(a)
                if acting == 0:
                    sum_p0 += reward
                else:
                    sum_p1 += reward
            assert sum_p0 >= 0.0, 'hp_delta=1 → dealer reward must be non-negative'
            assert sum_p1 >= 0.0
            # At least one player must have dealt damage across a 1v1
            # random-rollout episode that terminated.
            assert (sum_p0 + sum_p1) > 0.0

    def test_hp_taken_penalty_credits_receiver(self):
        """hp_taken_penalty=1 alone → each player's reward is
        non-positive (they only lose reward when they take damage)."""
        rs = {'hp_taken_penalty': 1.0}
        rng = np.random.default_rng(5)
        with make_env(['赤蝶'], ['墨客'], reward_shaping=rs) as env:
            for _ in range(600):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                a = int(rng.integers(0, len(kinds)))
                _, reward, _, _ = env.step(a)
                assert reward <= 0.0, f'hp_taken_penalty should never produce positive reward, got {reward}'


class TestResetZerosAccumulator:
    def test_reset_clears_reward_events(self):
        """engine.ResetDynamicState zeros RewardAccum. This test pins the
        behavior: after some damage and a reset, the next step sees
        zero delta in a purely-terminal-shaped env."""
        rng = np.random.default_rng(9)
        with make_env(['赤蝶'], ['墨客']) as env:
            # Play a few steps to accumulate reward events.
            for _ in range(10):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                a = int(rng.integers(0, len(kinds)))
                env.step(a)
            # Snapshot events post-play, reset, check they're zeroed.
            env.reset(seed=123)
            ev_p0 = env._engine.get_reward_events(0)
            ev_p1 = env._engine.get_reward_events(1)
            assert np.all(ev_p0 == 0), f'P0 RewardEvents not zeroed after reset: {ev_p0}'
            assert np.all(ev_p1 == 0), f'P1 RewardEvents not zeroed after reset: {ev_p1}'


class TestComputeShapedRewardUnit:
    """Direct unit tests of compute_shaped_reward — decouples the
    arithmetic from engine-driven episodes so a failure here pinpoints
    the formula vs the wiring."""

    def _ev(self, **kw):
        from gicg_env._constants import REWARD_EVENTS_FIELDS

        arr = np.zeros(len(REWARD_EVENTS_FIELDS), dtype=np.int32)
        idx = {n: i for i, n in enumerate(REWARD_EVENTS_FIELDS)}
        for k, v in kw.items():
            arr[idx[k]] = v
        return arr

    def test_hp_delta_isolation(self):
        rs = RewardShaping(hp_delta=1.0)
        before = self._ev()
        after = self._ev(damage_dealt=5, damage_received=3)  # receiver term is 0-weighted
        r = compute_shaped_reward(rs, before, after, done=False, winner=-1, me=0)
        assert r == 5.0

    def test_hp_taken_penalty_isolation(self):
        rs = RewardShaping(hp_taken_penalty=1.1)
        before = self._ev()
        after = self._ev(damage_dealt=5, damage_received=3)
        r = compute_shaped_reward(rs, before, after, done=False, winner=-1, me=0)
        assert r == pytest.approx(-3.3)

    def test_kill_bonus_isolation(self):
        rs = RewardShaping(kill_bonus=10.0)
        before = self._ev()
        after = self._ev(kills=2)
        r = compute_shaped_reward(rs, before, after, done=False, winner=-1, me=0)
        assert r == 20.0

    def test_death_penalty_isolation(self):
        rs = RewardShaping(death_penalty=8.0)
        before = self._ev()
        after = self._ev(deaths=1)
        r = compute_shaped_reward(rs, before, after, done=False, winner=-1, me=0)
        assert r == -8.0

    def test_terminal_win_bonus_only_at_done(self):
        rs = RewardShaping(terminal_win=60.0, terminal_loss=60.0)
        before = self._ev()
        after = self._ev()
        # Not done → no terminal contribution even when winner is set
        r0 = compute_shaped_reward(rs, before, after, done=False, winner=0, me=0)
        assert r0 == 0.0
        # Done, me=winner → +60
        r1 = compute_shaped_reward(rs, before, after, done=True, winner=0, me=0)
        assert r1 == 60.0
        # Done, me=loser → -60
        r2 = compute_shaped_reward(rs, before, after, done=True, winner=0, me=1)
        assert r2 == -60.0
        # Draw (winner=2) → 0 regardless of me
        r3 = compute_shaped_reward(rs, before, after, done=True, winner=2, me=0)
        assert r3 == 0.0
        r4 = compute_shaped_reward(rs, before, after, done=True, winner=2, me=1)
        assert r4 == 0.0
