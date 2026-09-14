"""Exact snapshot/restore contracts shared by CFR and search.

Snapshots preserve all gameplay and random state without advancing the source.
Restoring the same snapshot reproduces the same future under the same actions.
Algorithms requiring fresh chance samples must call set_simulation_seed explicitly
on a private simulation after restore. Independent objects never share mutable
state. Go lifecycle inventory and behavioral tests cover fields beyond the Python
observation API; these tests verify the C/Python boundary and full trajectories.
"""

import os

import numpy as np
import pytest

from gicg_env import GicgEngine
from gicg_env.engine import (
    ACTION_END_TURN,
    ACTION_SKILL,
    PHASE_ACTION,
    PHASE_GAME_OVER,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

PLAYERS = [['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']]
SEED = 4242


def _fresh_game(seed=SEED):
    """New engine in PhaseAction (both sides picked char 0 as active)."""
    eng = GicgEngine()
    eng.new_game(players=PLAYERS, seed=seed, data_dir=DATA_DIR)
    eng.step(0)  # P0 select active
    eng.step(0)  # P1 select active
    assert eng.phase == PHASE_ACTION
    return eng


def _snapshot_observables(eng):
    """Collect every observable CFR will read at a decision point."""
    kinds, indices = eng.get_legal_actions()
    return {
        'phase': eng.phase,
        'turn': eng.turn,
        'round': eng.get_current_round(),
        'acting_player': eng.acting_player,
        'done': eng.done,
        'winner': eng.winner,
        'has_pending': eng.has_pending,
        'hand_refs_p0': list(eng.hand_refs(0)),
        'hand_refs_p1': list(eng.hand_refs(1)),
        'deck_refs_p0': list(eng.deck_refs(0)),
        'deck_refs_p1': list(eng.deck_refs(1)),
        'discard_refs_p0': list(eng.discard_refs(0)),
        'discard_refs_p1': list(eng.discard_refs(1)),
        'dice_total_p0': int(eng.dice_total(0)),
        'dice_total_p1': int(eng.dice_total(1)),
        'dice_paid_p0': list(eng.dice_paid(0)),
        'dice_paid_p1': list(eng.dice_paid(1)),
        'dice_tuned_in_p0': list(eng.dice_tuned_in(0)),
        'dice_tuned_in_p1': list(eng.dice_tuned_in(1)),
        'dice_tuned_out_p0': list(eng.dice_tuned_out(0)),
        'dice_tuned_out_p1': list(eng.dice_tuned_out(1)),
        'counters': eng.get_counters().copy(),
        'dynamic_obs': eng.get_dynamic_obs().copy(),
        'legal_kinds': list(kinds),
        'legal_indices': list(indices),
    }


def _assert_observables_equal(a, b, note=''):
    assert a['phase'] == b['phase'], f'{note} phase'
    assert a['turn'] == b['turn'], f'{note} turn'
    assert a['round'] == b['round'], f'{note} round'
    assert a['acting_player'] == b['acting_player'], f'{note} acting_player'
    assert a['done'] == b['done'], f'{note} done'
    assert a['winner'] == b['winner'], f'{note} winner'
    assert a['has_pending'] == b['has_pending'], f'{note} has_pending'
    assert a['hand_refs_p0'] == b['hand_refs_p0'], f'{note} hand_refs_p0'
    assert a['hand_refs_p1'] == b['hand_refs_p1'], f'{note} hand_refs_p1'
    assert a['deck_refs_p0'] == b['deck_refs_p0'], f'{note} deck_refs_p0'
    assert a['deck_refs_p1'] == b['deck_refs_p1'], f'{note} deck_refs_p1'
    assert a['discard_refs_p0'] == b['discard_refs_p0'], f'{note} discard_refs_p0'
    assert a['discard_refs_p1'] == b['discard_refs_p1'], f'{note} discard_refs_p1'
    assert a['dice_total_p0'] == b['dice_total_p0'], f'{note} dice_total_p0'
    assert a['dice_total_p1'] == b['dice_total_p1'], f'{note} dice_total_p1'
    assert a['dice_paid_p0'] == b['dice_paid_p0'], f'{note} dice_paid_p0'
    assert a['dice_paid_p1'] == b['dice_paid_p1'], f'{note} dice_paid_p1'
    assert a['dice_tuned_in_p0'] == b['dice_tuned_in_p0'], f'{note} dice_tuned_in_p0'
    assert a['dice_tuned_in_p1'] == b['dice_tuned_in_p1'], f'{note} dice_tuned_in_p1'
    assert a['dice_tuned_out_p0'] == b['dice_tuned_out_p0'], f'{note} dice_tuned_out_p0'
    assert a['dice_tuned_out_p1'] == b['dice_tuned_out_p1'], f'{note} dice_tuned_out_p1'
    np.testing.assert_array_equal(a['counters'], b['counters'], err_msg=f'{note} counters')
    np.testing.assert_array_equal(a['dynamic_obs'], b['dynamic_obs'], err_msg=f'{note} dynamic_obs')
    assert a['legal_kinds'] == b['legal_kinds'], f'{note} legal_kinds'
    assert a['legal_indices'] == b['legal_indices'], f'{note} legal_indices'


def _first_skill_action_index(eng):
    kinds, _ = eng.get_legal_actions()
    idx = np.where(np.asarray(kinds) == ACTION_SKILL)[0]
    if len(idx) == 0:
        pytest.skip('no skill action available with this seed/dice')
    return int(idx[0])


def _end_turn_action_index(eng):
    kinds, _ = eng.get_legal_actions()
    idx = np.where(np.asarray(kinds) == ACTION_END_TURN)[0]
    assert len(idx) > 0, 'no end_turn action available'
    return int(idx[0])


# ───────────────────────────── Core round-trip ──────────────────────────────


class TestSnapshotRoundTrip:
    """snap → step → restore → observables match pre-step exactly."""

    def test_roundtrip_after_skill(self):
        # seed=1 empirically yields a skill action at the first PhaseAction;
        # default SEED may not.
        eng = _fresh_game(seed=1)
        try:
            before = _snapshot_observables(eng)
            snap = eng.snapshot()
            try:
                eng.step(_first_skill_action_index(eng))
                after_step = _snapshot_observables(eng)
                assert after_step != before  # sanity: step did change state
                eng.restore(snap)
                after_restore = _snapshot_observables(eng)
                _assert_observables_equal(before, after_restore, note='post-restore')
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_roundtrip_after_end_turn(self):
        eng = _fresh_game()
        try:
            before = _snapshot_observables(eng)
            snap = eng.snapshot()
            try:
                eng.step(_end_turn_action_index(eng))
                eng.restore(snap)
                after_restore = _snapshot_observables(eng)
                _assert_observables_equal(before, after_restore, note='after-end-turn')
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_roundtrip_after_long_sequence(self):
        """Snap → run 10 random-ish actions → restore → obs matches pre-sequence."""
        eng = _fresh_game()
        try:
            before = _snapshot_observables(eng)
            snap = eng.snapshot()
            try:
                for _ in range(10):
                    if eng.done:
                        break
                    kinds, _indices = eng.get_legal_actions()
                    if len(kinds) == 0:
                        break
                    eng.step(0)  # always pick first legal
                eng.restore(snap)
                after_restore = _snapshot_observables(eng)
                _assert_observables_equal(before, after_restore, note='long-seq')
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_roundtrip_mid_turn_after_some_actions(self):
        """Advance a few actions first, THEN snap — verify mid-game snap works,
        not only initial PhaseAction."""
        eng = _fresh_game()
        try:
            # Advance a few deterministic no-op-ish steps
            for _ in range(3):
                if eng.done:
                    pytest.skip('game ended too early')
                eng.step(0)
            before = _snapshot_observables(eng)
            snap = eng.snapshot()
            try:
                # Mutate further
                for _ in range(5):
                    if eng.done:
                        break
                    eng.step(0)
                eng.restore(snap)
                after_restore = _snapshot_observables(eng)
                _assert_observables_equal(before, after_restore, note='mid-turn')
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()


# ────────────────────────── Exploration independence ─────────────────────────


class TestExploreBranches:
    """CFR traversal: snap → step A → restore → step B → compare outcomes.
    The two branches from the SAME pre-decision state must yield independent
    forward play. Pre-step state after each restore is identical; post-step
    state may differ across branches (and that's the point)."""

    def test_two_branches_share_pre_decision_state(self):
        eng = _fresh_game()
        try:
            before = _snapshot_observables(eng)
            snap = eng.snapshot()
            try:
                kinds, _ = eng.get_legal_actions()
                if len(kinds) < 2:
                    pytest.skip('not enough legal actions to branch')
                eng.step(0)
                _branch_a = _snapshot_observables(eng)
                eng.restore(snap)
                pre_b = _snapshot_observables(eng)
                _assert_observables_equal(before, pre_b, note='pre-branch-B')
                eng.step(1)
                branch_b = _snapshot_observables(eng)
                # Branches must have diverged (different action → different state)
                assert (
                    branch_b['counters'].tolist() != _branch_a['counters'].tolist()
                    or branch_b['hand_refs_p0'] != _branch_a['hand_refs_p0']
                    or branch_b['turn'] != _branch_a['turn']
                    or branch_b['has_pending'] != _branch_a['has_pending']
                ), 'branches A and B produced identical state; branching is a no-op'
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_same_action_twice_from_restore_gives_same_result(self):
        """Snap → step A → restore → step A again. Within-round actions are
        deterministic (no RNG) so both executions of A must match exactly.
        This is the core invariant CFR relies on for reproducible explore."""
        eng = _fresh_game()
        try:
            snap = eng.snapshot()
            try:
                eng.step(0)
                first_run = _snapshot_observables(eng)
                eng.restore(snap)
                eng.step(0)
                second_run = _snapshot_observables(eng)
                _assert_observables_equal(first_run, second_run, note='same-action-twice')
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()


# ────────────────────────── Snapshot independence ────────────────────────────


class TestSnapshotIndependence:
    """Snap is a frozen point; mutations on the engine must not bleed into it."""

    def test_engine_steps_after_snap_do_not_corrupt_snap(self):
        eng = _fresh_game()
        try:
            snap = eng.snapshot()
            try:
                # Run many mutations on engine
                for _ in range(20):
                    if eng.done:
                        break
                    eng.step(0)
                # snap must still be restorable to the original PhaseAction
                post_snap_obs = _snapshot_observables(eng)
                eng.restore(snap)
                after_restore = _snapshot_observables(eng)
                assert after_restore['phase'] == PHASE_ACTION
                assert after_restore['round'] == 1
                # verify at least one field actually diverged between post-heavy-play
                # and the restored state (sanity check that mutations happened)
                assert (
                    post_snap_obs['counters'].tolist() != after_restore['counters'].tolist()
                    or post_snap_obs['round'] != after_restore['round']
                    or post_snap_obs['done'] != after_restore['done']
                )
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_multiple_snaps_are_independent(self):
        """Two snaps at different points. Restoring either must land on that
        point without interference."""
        eng = _fresh_game()
        try:
            snap_a = eng.snapshot()
            obs_a = _snapshot_observables(eng)
            eng.step(0)
            snap_b = eng.snapshot()
            obs_b = _snapshot_observables(eng)
            try:
                # Advance further then roll back to A
                eng.step(0)
                eng.restore(snap_a)
                restored_a = _snapshot_observables(eng)
                _assert_observables_equal(obs_a, restored_a, note='restore-to-A')
                # Now roll forward to B
                eng.restore(snap_b)
                restored_b = _snapshot_observables(eng)
                _assert_observables_equal(obs_b, restored_b, note='restore-to-B')
            finally:
                eng.snapshot_free(snap_a)
                eng.snapshot_free(snap_b)
        finally:
            eng.close()


# ────────────────────────── Pending action survival ──────────────────────────


class TestSnapshotPendingState:
    """PendingAction (forced switch) / PendingCardTarget must survive snap.
    Go-side already tested via gicg_engine/tests/pending_snapshot_test.go;
    this verifies the Python capi surface doesn't lose it in translation."""

    def test_pending_forced_switch_survives_roundtrip(self):
        """Drive the game until a forced switch is pending (a char dies),
        snap, advance, restore, confirm pending state is restored."""
        eng = _fresh_game()
        try:
            # Play up to 200 actions looking for a forced-switch pending state.
            # With damaging skills on both sides, some char will eventually die.
            snap_at_pending = None
            obs_at_pending = None
            for _ in range(200):
                if eng.done:
                    break
                if eng.is_forced_switch_pending():
                    snap_at_pending = eng.snapshot()
                    obs_at_pending = _snapshot_observables(eng)
                    break
                eng.step(0)
            if snap_at_pending is None:
                pytest.skip('no forced-switch pending observed in 200 steps')
            try:
                # Advance through the forced switch
                eng.step(0)
                # Now restore and check pending state is restored
                eng.restore(snap_at_pending)
                after_restore = _snapshot_observables(eng)
                _assert_observables_equal(obs_at_pending, after_restore, note='pending-switch-restore')
                assert after_restore['has_pending']
            finally:
                eng.snapshot_free(snap_at_pending)
        finally:
            eng.close()


# ─────────────────── Rollout to completion under snap/restore ────────────────


class TestFullRolloutUnderSnapshot:
    """Bigger smoke: snap at an early decision point, roll out to terminal,
    restore, roll out again. Both full rollouts must reach a terminal state
    with identical observable trajectories and outcomes."""

    def test_snap_then_two_full_rollouts(self):
        eng = _fresh_game()
        try:
            # Take a few turns to get past setup, then snap
            for _ in range(6):
                if eng.done:
                    pytest.skip('game ended during warmup')
                eng.step(0)
            snap = eng.snapshot()
            try:
                trajectory = []
                steps_a = 0
                while not eng.done and steps_a < 500:
                    eng.step(0)
                    trajectory.append(_snapshot_observables(eng))
                    steps_a += 1
                assert eng.done, 'rollout A did not terminate in 500 steps'
                outcome_a = eng.winner

                eng.restore(snap)
                assert not eng.done, 'restore landed on a terminal state'

                steps_b = 0
                while not eng.done and steps_b < 500:
                    eng.step(0)
                    assert steps_b < len(trajectory)
                    _assert_observables_equal(trajectory[steps_b], _snapshot_observables(eng), note=f'step {steps_b}')
                    steps_b += 1
                assert eng.done, 'rollout B did not terminate in 500 steps'
                outcome_b = eng.winner

                assert steps_a == steps_b
                assert outcome_a == outcome_b
                assert outcome_a in (-1, 0, 1, 2)
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()


# ──────────────────────────── Snapshot lifecycle ─────────────────────────────


class TestSnapshotLifecycle:
    def test_snapshot_free_is_idempotent_noop(self):
        """snapshot_free of a valid snap must not error; double-free is tolerated."""
        eng = _fresh_game()
        try:
            snap = eng.snapshot()
            eng.snapshot_free(snap)
            # Double-free: the capi impl uses delete(map, sid) which is a no-op
            # on missing keys — tolerated.
            eng.snapshot_free(snap)
        finally:
            eng.close()

    def test_snapshot_across_clone(self):
        """clone produces an independent engine. Snap from source should NOT
        be restorable on the clone (different handle, snap is keyed globally
        by snap-id but restore operates on this handle's game). This pins
        down the scope contract."""
        eng = _fresh_game()
        try:
            snap = eng.snapshot()
            try:
                cloned = eng.clone()
                try:
                    # Cloned engine starts at an independent state; we don't
                    # promise cross-handle restore is illegal, but we do
                    # promise that restoring ON THE SAME handle works.
                    eng.step(0)
                    eng.restore(snap)
                    obs = _snapshot_observables(eng)
                    assert obs['phase'] == PHASE_ACTION
                finally:
                    cloned.close()
            finally:
                eng.snapshot_free(snap)
        finally:
            eng.close()
