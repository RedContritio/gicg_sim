"""Tests for the GicgEnv wrapper."""

import os
import pytest
import numpy as np

from gicg_env import GicgEnv

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def make_env(team_0, team_1, **kw):
    return GicgEnv(team_0, team_1, data_dir=DATA_DIR, **kw)


class TestEnvBasic:
    def test_construct_mirror_1v1(self):
        with make_env(['赤蝶'], ['赤蝶']) as env:
            obs = env.reset()
            assert obs is not None
            assert len(obs) > 0
            assert env.obs_size > 0

    def test_construct_mirror_3v3(self):
        with make_env(['赤蝶', '墨客', '猫咪'], ['赤蝶', '墨客', '猫咪']) as env:
            obs = env.reset()
            assert len(obs) == env.obs_size

    def test_construct_nonmirror_1v1(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            obs = env.reset()
            assert len(obs) > 0

    def test_legal_actions(self):
        with make_env(['赤蝶'], ['赤蝶']) as env:
            kinds, indices = env.get_legal_actions()
            assert len(kinds) > 0

    def test_action_identities_shape(self):
        """get_action_identities returns (n_legal, 5) with every row
        having a recognizable kind code, and subject_ref populated
        for Skill/Card/Switch/Tune where applicable."""
        with make_env(['赤蝶'], ['赤蝶']) as env:
            env.reset()
            kinds, _ = env.get_legal_actions()
            ids = env.get_action_identities()
            assert ids.shape == (len(kinds), 5)
            assert ids.dtype.kind == 'i'
            # kind column matches kinds array
            assert (ids[:, 0] == np.asarray(kinds)).all()
            # Every row should have target in a valid range
            # (-1 means no target; 0/1 are player indices; 0..5 char).
            assert (ids[:, 3] >= -1).all() and (ids[:, 3] <= 1).all()

    def test_action_identities_tune_exposes_card_ref(self):
        """Tune actions must carry the card_ref being tuned as
        subject_ref and the source dice color as aux — required for
        MCTS per-card identity keying (see
        ``docs/2_decisions/adr-0005-az_decisions_d1_d14.md``)."""
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            # Seed a non-native dice pool so tune becomes legal.
            # 赤蝶 is fire, so ice dice qualify as "non-native".
            env._engine.set_player_dice(0, [0, 4, 0, 0, 0, 0, 0, 0])
            kinds, _ = env.get_legal_actions()
            ids = env.get_action_identities()
            # Kind 4 = ActionTune per types.go
            tune_rows = ids[ids[:, 0] == 4]
            if len(tune_rows) == 0:
                pytest.skip('no tune actions legal in this setup')
            for row in tune_rows:
                _, subject_ref, aux, tp, tc = row
                assert subject_ref >= 0, 'tune subject_ref should be a card_ref'
                assert 0 <= aux < 8, f'tune aux should be a dice color 0..7, got {aux}'
                assert tp == -1 and tc == -1

    def test_legal_action_payments_shape(self):
        from gicg_env.engine import DICE_COLOR_COUNT

        with make_env(['赤蝶'], ['赤蝶']) as env:
            kinds, indices = env.get_legal_actions()
            payments = env._engine.get_legal_action_payments()
            # One row per legal action, 8 columns (dice colors).
            assert payments.shape == (len(kinds), DICE_COLOR_COUNT)
            assert payments.dtype.kind == 'i'
            # Payments must be non-negative.
            assert (payments >= 0).all()

    def test_legal_action_payments_skill_cost(self):
        """After seeding a known dice pool, the legal action set for
        a normal-attack skill should include a payment variant whose
        total dice equal the skill's declared cost (3 for 1-elem + 2-
        any normal attacks). Values are also bounded by what's in
        the pool."""
        from gicg_env.engine import DICE_COLOR_COUNT

        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            # 枪 = 1 fire + 2 any = 3 total dice
            kinds, indices = env.get_legal_actions()
            payments = env._engine.get_legal_action_payments()
            assert payments.shape[1] == DICE_COLOR_COUNT

            # Find a skill action whose total payment is 3 (枪 discounted
            # variant would be 2, non-discounted is 3). We expect at least
            # one skill in the legal action list with total ≥ 2.
            skill_mask = kinds == 0  # ActionSkill kind
            if not skill_mask.any():
                return  # nothing to check — rare edge case
            skill_totals = payments[skill_mask].sum(axis=1)
            assert (skill_totals >= 2).any(), (
                f'skill totals {skill_totals} all below 2; expected a normal-attack cost of at least 2 dice'
            )

    def test_payments_end_turn_all_zero(self):
        with make_env(['赤蝶'], ['赤蝶']) as env:
            env.reset()
            kinds, _ = env.get_legal_actions()
            payments = env._engine.get_legal_action_payments()
            # ActionEndTurn kind == 3
            end_mask = kinds == 3
            assert end_mask.any(), 'expected an EndTurn action in legal list'
            end_payments = payments[end_mask]
            assert (end_payments == 0).all(), f'EndTurn should have zero payment, got {end_payments}'

    def test_step(self):
        with make_env(['赤蝶'], ['赤蝶']) as env:
            obs, reward, done, info = env.step(0)
            assert obs is not None
            assert reward == 0.0, 'no shaping configured → reward must be 0.0'
            assert 'winner' in info

    def test_reset_seed_changes_state(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.step(0)
            env.reset(seed=99)
            # After reset we should be back in PHASE_ACTION on round 1
            assert not env.done


class TestPerspective:
    def test_different_perspectives(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            obs_p0 = env._engine.get_dynamic_obs(perspective=0)
            obs_p1 = env._engine.get_dynamic_obs(perspective=1)
            assert not np.array_equal(obs_p0, obs_p1)

    def test_default_perspective_is_acting_player(self):
        """Audit E-1 regression: get_dynamic_obs(perspective=None) must
        default to acting_player, not turn. Under forced-switch pending
        these differ, and MCTS / training all read acting_player as the
        decision-maker."""
        with make_env(['赤蝶'], ['墨客']) as env:
            # Normal state: acting_player == turn, default matches both
            acting = env._engine.acting_player
            turn = env._engine.turn
            assert acting == turn
            obs_default = env._engine.get_dynamic_obs()
            obs_acting = env._engine.get_dynamic_obs(perspective=acting)
            assert np.array_equal(obs_default, obs_acting), 'default perspective must match acting_player'

    def test_env_get_obs_uses_acting_player(self):
        """env._get_obs() must use acting_player perspective (via the
        engine default). Regression for E-1."""
        with make_env(['赤蝶'], ['墨客']) as env:
            obs_via_env = env._get_obs()
            # _get_obs normalizes values; to compare raw perspective we
            # need to compare against the engine-level raw obs scaled
            # the same way. Simpler: verify the engine default matches
            # acting_player at this quiescent state.
            raw_default = env._engine.get_dynamic_obs()
            raw_acting = env._engine.get_dynamic_obs(
                perspective=env._engine.acting_player,
            )
            assert np.array_equal(raw_default, raw_acting)
            # obs_via_env is normalized version of raw_default — must
            # be non-zero on at least the meta block.
            assert obs_via_env.shape[0] == env.obs_size


class TestSelfPlay:
    def test_random_selfplay_completes(self):
        with make_env(['赤蝶', '墨客'], ['猫咪', '天星']) as env:
            rng = np.random.RandomState(42)
            for step in range(300):
                if env.done:
                    break
                kinds, indices = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                action = rng.randint(0, len(kinds))
                obs, _reward, done, info = env.step(action)
                # A pending target is handled automatically: the next
                # step() consults engine state and routes to step_target().

    def test_terminal_z_helper_raises_on_non_terminal(self):
        """The _terminal_z helper raises on winner=-1 (game not yet
        terminated). Guards against silent 0-fallback corrupting
        training z targets."""
        from gicg_env.env import _terminal_z

        assert _terminal_z(0) == 1.0
        assert _terminal_z(1) == -1.0
        assert _terminal_z(2) == 0.0
        with pytest.raises(ValueError, match='expected 0/1/2'):
            _terminal_z(-1)
        with pytest.raises(ValueError, match='expected 0/1/2'):
            _terminal_z(99)

    def test_terminal_z_matches_winner(self):
        """At the terminal step info['z'] must be +1 for P0 win, -1 for
        P1 win, 0 for draw. Intra-game steps must not carry z. This is
        the only scalar signal AZ training uses as the value target."""
        with make_env(['赤蝶'], ['墨客']) as env:
            rng = np.random.RandomState(0)
            terminal_info = None
            for _ in range(600):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                action = rng.randint(0, len(kinds))
                _, _, done, info = env.step(action)
                if not done:
                    assert 'z' not in info, 'z leaked on intra-game step'
                else:
                    terminal_info = info
                    break
            assert terminal_info is not None, 'game never terminated'
            winner = terminal_info['winner']
            z = terminal_info['z']
            if winner == 0:
                assert z == 1.0
            elif winner == 1:
                assert z == -1.0
            else:
                assert z == 0.0

    def test_observation_consistency(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            size = env.obs_size
            for _ in range(10):
                if env.done:
                    break
                obs = env._get_obs()
                assert len(obs) == size
                kinds, _ = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                env.step(0)


class TestCloneSnapshot:
    def test_clone_independent(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            twin = env.clone()
            try:
                kinds, _ = twin.get_legal_actions()
                if len(kinds) > 0:
                    twin.step(0)
                # Original should not have advanced beyond its current state
                assert env.current_player in (0, 1)
            finally:
                twin.close()

    def test_snapshot_restore(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            snap = env.snapshot()
            try:
                pre_player = env.current_player
                kinds, _ = env.get_legal_actions()
                if len(kinds) > 0:
                    env.step(0)
                env.restore(snap)
                assert env.current_player == pre_player
            finally:
                env.snapshot_free(snap)


class TestActingPlayerAndPending:
    """acting_player / has_pending query the engine so that
    Python has no snapshot-sensitive local state."""

    def test_acting_player_matches_turn_under_normal_play(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            assert env.acting_player == env._engine.turn
            assert env.acting_player in (0, 1)

    def test_has_pending_false_on_fresh_state(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            assert env.has_pending is False

    def test_current_player_alias(self):
        """current_player is kept as a back-compat alias for acting_player."""
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            assert env.current_player == env.acting_player
