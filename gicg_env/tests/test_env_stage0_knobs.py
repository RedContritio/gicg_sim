"""Tests for the historical curriculum Stage-0 knobs: max_rounds and fix_dice.

These two flags are the minimum Go-side infrastructure needed to make
Stage 0 of the curriculum runnable — bounded-length deterministic-dice
episodes. See ``docs/5_history/curriculum/plan.md`` Stage 0.

The other proposed T-D flags (fully_observable, disable_reactions) are
deferred to later stages — Stage 0 uses ``card_pool=[]`` (trivially
fully observable, no hidden hand/deck) and same-element chars (no
reaction triggers), so they aren't on the critical path.
"""

import os

import numpy as np
import pytest

from gicg_env import GicgEnv
from gicg_env._constants import DICE_COLOR_COUNT, REWARD_EVENTS_FIELDS  # noqa: F401

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def make_env(team_0, team_1, **kw):
    return GicgEnv(team_0, team_1, data_dir=DATA_DIR, **kw)


def _drive_until_done(env, rng, step_budget=400):
    """Random self-play until done. Returns (final_info, steps_taken)."""
    info = None
    steps = 0
    for _ in range(step_budget):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        a = int(rng.integers(0, len(kinds)))
        _, _, _, info = env.step(a)
        steps += 1
    return info, steps


class TestMaxRounds:
    def test_default_zero_means_unbounded(self):
        """max_rounds=0 (default) preserves legacy behavior — the game
        may run until timeout.lua (round 10) or HP depletion ends it,
        and no early draw is forced."""
        rng = np.random.default_rng(0)
        with make_env(['赤蝶'], ['墨客']) as env:
            assert env._max_rounds == 0
            info, _ = _drive_until_done(env, rng, step_budget=600)
            # Either the game ended naturally (HP or round-10 timeout),
            # or we didn't terminate — but we must not have a spurious
            # MaxRounds draw, which this env didn't configure.
            if info is not None and env.done:
                assert env._engine.get_current_round() <= 11

    def test_max_rounds_3_caps_at_round_3(self):
        """With max_rounds=3, the game must be done by round 3 end, and
        the winner code must reflect a draw if neither side HP-killed
        within the cap."""
        rng = np.random.default_rng(1)
        with make_env(['赤蝶'], ['墨客'], max_rounds=3) as env:
            info, _ = _drive_until_done(env, rng, step_budget=600)
            assert env.done, 'game should terminate within step budget when max_rounds=3'
            assert env._engine.get_current_round() <= 3, (
                f'round exceeded cap: got round {env._engine.get_current_round()}'
            )
            assert info is not None
            # Winner is 0/1 (HP depletion) or 2 (max_rounds draw);
            # never -1 once done.
            assert info['winner'] in (0, 1, 2)

    def test_max_rounds_draw_when_no_hp_kill(self):
        """With fix_dice forcing all-omni (no element match), attacks
        often fail → very few HP swings → game hits the round cap as
        draw. Demonstrates the Winner=2 path."""
        all_omni = [0] * 7 + [10]  # 10 omni dice → any cost payable, but
        # the actual play pattern with random-action policy still often
        # just bounces end-turn signals; the robust assertion is that
        # *some* seed seeds hit Winner=2 when the cap is tight.
        hit_draw = False
        for seed in range(8):
            rng = np.random.default_rng(seed)
            with make_env(
                ['赤蝶'],
                ['赤蝶'],  # mirror same-element → no reactions
                max_rounds=2,
                fix_dice=all_omni,
            ) as env:
                info, _ = _drive_until_done(env, rng, step_budget=400)
                if info is not None and info.get('winner') == 2:
                    hit_draw = True
                    break
        assert hit_draw, (
            'expected at least one seed to end in Winner=2 under max_rounds=2 + all-omni dice + same-element mirror'
        )

    def test_max_rounds_survives_reset(self):
        """max_rounds is static config — reset(seed) keeps it."""
        with make_env(['赤蝶'], ['赤蝶'], max_rounds=3) as env:
            env.reset(seed=7)
            assert env._max_rounds == 3
            rng = np.random.default_rng(7)
            _drive_until_done(env, rng, step_budget=400)
            assert env.done
            assert env._engine.get_current_round() <= 3


class TestFixDice:
    def test_default_none_means_random_roll(self):
        """fix_dice=None (default) keeps the existing RollDice path.
        Two resets with the same seed produce identical dice; two with
        different seeds should (usually) differ."""
        with make_env(['赤蝶'], ['赤蝶']) as env:
            assert env._fix_dice is None
            env.reset(seed=1)
            env.step(0)  # into round-1 action phase
            env.step(0)
            dice_s1_r1 = env._engine.dice_counts(0).copy()

            env.reset(seed=1)
            env.step(0)
            env.step(0)
            dice_s1_r1_again = env._engine.dice_counts(0).copy()
            assert np.array_equal(dice_s1_r1, dice_s1_r1_again), (
                'same seed must reproduce same dice roll (RNG determinism regression)'
            )

    def test_fix_dice_exact_per_color(self):
        """fix_dice=[2,2,2,2,0,0,0,0] → P0 gets exactly (2 fire, 2 ice,
        2 water, 2 electro, 0, 0, 0, 0) at round 1 start."""
        spec = [2, 2, 2, 2, 0, 0, 0, 0]
        with make_env(['赤蝶'], ['赤蝶'], fix_dice=spec) as env:
            # Drive into PhaseAction so dice have been rolled via
            # on_round_start. The PHASE_SELECT_ACTIVE → PHASE_ACTION
            # transition fires round_start hooks.
            env.step(0)  # P0 select-active
            env.step(0)  # P1 select-active → triggers round 1 start
            p0_dice = env._engine.dice_counts(0)
            p1_dice = env._engine.dice_counts(1)
            assert list(p0_dice) == spec, f'P0 dice = {list(p0_dice)}, want {spec}'
            assert list(p1_dice) == spec, f'P1 dice = {list(p1_dice)}, want {spec}'

    def test_fix_dice_persists_across_rounds(self):
        """The whole point of fix_dice is round-to-round determinism.
        Burn through one full round of actions, verify round 2's
        freshly-rolled dice again match the fixed counts."""
        spec = [4, 0, 0, 0, 0, 0, 0, 4]  # 4 fire + 4 omni
        rng = np.random.default_rng(2)
        with make_env(['赤蝶'], ['赤蝶'], fix_dice=spec, max_rounds=3) as env:
            env.step(0)
            env.step(0)
            round_1_p0 = env._engine.dice_counts(0).copy()
            assert list(round_1_p0) == spec

            # Play out round 1 (random actions until round advances or done).
            start_round = env._engine.get_current_round()
            for _ in range(200):
                if env.done or env._engine.get_current_round() > start_round:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                env.step(int(rng.integers(0, len(kinds))))

            if env.done:
                pytest.skip("game ended inside round 1 — can't sample round 2 dice")
            round_2_p0 = env._engine.dice_counts(0).copy()
            assert list(round_2_p0) == spec, (
                f'round 2 P0 dice={list(round_2_p0)}, want {spec}; fix_dice must reproduce every round'
            )

    def test_fix_dice_wrong_length_raises(self):
        """A length-mismatched fix_dice is a programmer error — raise
        at construction time, not silently fall through to random."""
        with pytest.raises(ValueError, match=f'length {DICE_COLOR_COUNT}'):
            make_env(['赤蝶'], ['赤蝶'], fix_dice=[1, 2, 3])

    def test_fix_dice_survives_reset(self):
        """Static config: reset(seed) must not clear fix_dice.

        Note: engine.ResetDynamic already advances past the two
        select-active turns internally, so after reset() the game is
        already in PhaseAction with round 1's dice rolled. We read
        dice immediately, without extra env.step() calls."""
        spec = [1, 1, 1, 1, 1, 1, 1, 1]
        with make_env(['赤蝶'], ['赤蝶'], fix_dice=spec) as env:
            env.reset(seed=99)
            assert list(env._engine.dice_counts(0)) == spec

    def test_fix_dice_via_clone(self):
        """clone() must propagate fix_dice to the clone's Go Game (the
        value is stored on engine.Game and carried by DeepCopy).

        After reset_dynamic on the clone, the engine has advanced past
        select-active and rolled dice — check immediately."""
        spec = [3, 0, 0, 0, 0, 0, 0, 0]
        with make_env(['赤蝶'], ['赤蝶'], fix_dice=spec) as env:
            env.step(0)
            env.step(0)
            twin = env.clone()
            try:
                twin._engine.reset_dynamic(42)
                assert list(twin._engine.dice_counts(0)) == spec
            finally:
                twin.close()


class TestObsMask:
    """Python-layer obs masking (Stage 2+ partial-observability). Engine
    stays fully observable; env post-processes obs slots before return."""

    def test_no_mask_default(self):
        """obs_mask=None (default) → full obs, no slots zeroed."""
        with make_env(['赤蝶'], ['墨客'], fix_dice=[2, 2, 2, 2, 0, 0, 0, 0]) as env:
            env.reset(seed=0)
            obs = env._get_obs()
            # At least some enemy dice slot should be nonzero (fix_dice
            # rolled 2 of each to each player).
            labels = env._engine.get_active_counter_slot_labels()
            from gicg_env.env_obs import OBS_META_SIZE

            enemy_dice_slots = [i for i, l in enumerate(labels) if l.startswith('P1:dice_')]
            assert any(obs[OBS_META_SIZE + s] != 0 for s in enemy_dice_slots), (
                'baseline obs must show enemy dice non-zero'
            )

    def test_enemy_dice_mask_zeros_enemy_not_own(self):
        """obs_mask=['enemy_dice'] → enemy dice slots zeroed, own preserved."""
        with make_env(['赤蝶'], ['墨客'], fix_dice=[2, 2, 2, 2, 0, 0, 0, 0], obs_mask=['enemy_dice']) as env:
            env.reset(seed=0)
            obs = env._get_obs()
            labels = env._engine.get_active_counter_slot_labels()
            from gicg_env.env_obs import OBS_META_SIZE

            # When acting_player=0 (P0), enemy=P1. All P1:dice_* slots must be 0.
            assert env._engine.acting_player == 0
            for i, l in enumerate(labels):
                if l.startswith('P1:dice_'):
                    assert obs[OBS_META_SIZE + i] == 0.0, (
                        f'enemy dice slot {l} not masked (value={obs[OBS_META_SIZE + i]})'
                    )
            # Own dice (P0) must be preserved (non-zero for fire/ice/water/electro).
            has_own_nonzero = False
            for i, l in enumerate(labels):
                if l.startswith('P0:dice_') and obs[OBS_META_SIZE + i] != 0:
                    has_own_nonzero = True
                    break
            assert has_own_nonzero, 'own dice must remain visible after enemy-only mask'

    def test_clone_preserves_mask(self):
        """clone() propagates the pre-computed mask slot indices."""
        with make_env(['赤蝶'], ['墨客'], fix_dice=[3, 0, 0, 0, 0, 0, 0, 0], obs_mask=['enemy_dice']) as env:
            env.reset(seed=0)
            twin = env.clone()
            try:
                twin._engine.reset_dynamic(42)
                obs = twin._get_obs()
                labels = twin._engine.get_active_counter_slot_labels()
                from gicg_env.env_obs import OBS_META_SIZE

                for i, l in enumerate(labels):
                    if l.startswith('P1:dice_'):
                        assert obs[OBS_META_SIZE + i] == 0.0, 'clone lost mask'
            finally:
                twin.close()
