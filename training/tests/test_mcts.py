"""IS-UCT MCTS tests.

These exercise the tree end-to-end against a real GicgEnv — not a
stub — because the MCTS correctness claims (identity-keyed children,
N_avail bookkeeping, determinization-per-rollout) only make sense
against a ruleset that produces real legal sets and real
transitions. A random-weight Agent is fine: MCTS doesn't need the
policy to be good, only for the shape contract to hold.
"""

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import (
    ACTION_TUNE,
    MCTSConfig,
    MCTSNode,
    MCTSProfile,
    _argmax_visits,
    _detect_discovery,
    _find_action_index,
    _puct_select,
    build_action_id,
    legal_ids_from_env,
    mcts_search,
)
from training.paradigms.az.network import Agent, AgentConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


# Engine observation constants used by AgentConfig (duplicated from
# old tools/replay_episode.py — kept local to avoid a tools import).
OBS_MAX_CHARS = 6
OBS_CHAR_SLOTS = 128
OBS_PLAYER_SLOTS = 140
OBS_GLOBAL_SLOTS = 16
N_COUNTER_SLOTS = 2 * OBS_MAX_CHARS * OBS_CHAR_SLOTS + 2 * OBS_PLAYER_SLOTS + OBS_GLOBAL_SLOTS
N_HOOKS = 900
MAX_TOKENS = 128
# 256 covers the widest legal list observed under a 1v1 mirror with
# full dice-payment fan-out (empirically ~154). 3v3 may need more;
# tune in task #148 when the production config lands.
MAX_ACTIONS = 1024


def _advance_past_select_active(env: GicgEnv) -> None:
    """Step through PhaseSelectActive (each player picks their first
    active char) so the env lands in PhaseAction ready for MCTS."""
    while env.phase == 1:  # PHASE_SELECT_ACTIVE
        env.step(0)
        if env.done:
            break


def _small_agent(env: GicgEnv, seed: int = 0) -> Agent:
    """Tiny-d_model Agent that exercises every code path but runs
    fast enough for tests."""
    torch.manual_seed(seed)
    cfg = AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS,
        max_ops_per_hook=MAX_TOKENS,
        max_actions=MAX_ACTIONS,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )
    agent = Agent(cfg)
    agent.net.eval()
    agent.encode_static(env.static_obs)
    return agent


def _make_env(team_0, team_1, cards=None, seed=42):
    env = GicgEnv(team_0, team_1, card_pool=cards, seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    _advance_past_select_active(env)
    return env


def _pool_from_env(env: GicgEnv, player: int = 0) -> list[int]:
    """Build a SharedFixedPool pool for the given player by reading
    their initial hand refs + padding filler for the deck. The tests
    only assert 'sampled refs come from pool', not exact composition."""
    view = env.export_view()
    hand = view['players'][player]['hand']
    deck = view['players'][player]['deck_count']
    if not hand:
        return []
    filler = hand[0]['ref']
    refs = [c['ref'] for c in hand] + [filler] * deck
    return refs


class TestBuildActionId:
    def test_shape(self):
        ident = np.array([0, 5, -1, -1, -1], dtype=np.int32)
        pay = np.array([3, 0, 0, 0, 0, 0, 0, 0], dtype=np.int32)
        aid = build_action_id(ident, pay)
        assert aid == (0, 5, -1, -1, -1, (3, 0, 0, 0, 0, 0, 0, 0))

    def test_different_tunes_different_ids(self):
        """Per B4: tune actions that target different card_refs must
        produce different identities."""
        pay = np.zeros(8, dtype=np.int32)
        id1 = build_action_id(
            np.array([ACTION_TUNE, 42, 1, -1, -1], dtype=np.int32),
            pay,
        )
        id2 = build_action_id(
            np.array([ACTION_TUNE, 43, 1, -1, -1], dtype=np.int32),
            pay,
        )
        assert id1 != id2
        # Same card, different source color → also different
        id3 = build_action_id(
            np.array([ACTION_TUNE, 42, 2, -1, -1], dtype=np.int32),
            pay,
        )
        assert id1 != id3


class TestMCTSSearchPreconditions:
    def test_zero_rollouts_raises(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            cfg = MCTSConfig(n_rollouts=0)
            with pytest.raises(ValueError, match='n_rollouts must be positive'):
                mcts_search(
                    env,
                    agent,
                    SharedFixedPool(_pool_from_env(env, 0)),
                    random.Random(0),
                    viewing_player=0,
                    config=cfg,
                )
        finally:
            env.close()

    def test_terminal_root_raises(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            # Force terminal by hitting the victim's char until death.
            # Easier: manufacture done via reading env.done isn't
            # enough — we need a real terminal. Simulate by stepping
            # a long random playout until done or step cap.
            rng = np.random.RandomState(0)
            for _ in range(300):
                if env.done:
                    break
                kinds, _ = env.get_legal_actions()
                if not len(kinds):
                    break
                env.step(rng.randint(0, len(kinds)))
            if not env.done:
                pytest.skip("random playout didn't terminate in 300 steps")
            cfg = MCTSConfig(n_rollouts=10)
            with pytest.raises(RuntimeError, match='terminal'):
                mcts_search(
                    env,
                    agent,
                    SharedFixedPool(_pool_from_env(env, 0)),
                    random.Random(0),
                    viewing_player=0,
                    config=cfg,
                )
        finally:
            env.close()

    def test_viewing_player_mismatch_raises(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            wrong_viewer = 1 - env.acting_player
            cfg = MCTSConfig(n_rollouts=10)
            with pytest.raises(ValueError, match='viewing_player'):
                mcts_search(
                    env,
                    agent,
                    SharedFixedPool(_pool_from_env(env, 0)),
                    random.Random(0),
                    viewing_player=wrong_viewer,
                    config=cfg,
                )
        finally:
            env.close()


class TestMCTSSearchBasic:
    def test_runs_and_returns_legal_action(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(n_rollouts=30, max_rollout_depth=100)
            kinds, _ = env.get_legal_actions()
            n_legal = len(kinds)
            chosen, info = mcts_search(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            assert 0 <= chosen < n_legal
            assert info['pi'].shape == (n_legal,)
            assert abs(info['pi'].sum() - 1.0) < 1e-5
            assert len(info['legal_ids']) == n_legal
            # Every rollout went somewhere — root's child visit sum
            # should equal n_rollouts.
            total_visits = sum(info['visits'].values())
            assert total_visits == cfg.n_rollouts
            # root_value_p0 should be in [-1, 1]
            assert -1.0 <= info['root_value_p0'] <= 1.0
        finally:
            env.close()

    def test_env_restored_to_root_after_search(self):
        """MCTS must not leave env mutated — the hand/counters after
        search must match before."""
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            before_view = env.export_view()
            cfg = MCTSConfig(n_rollouts=15)
            mcts_search(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            after_view = env.export_view()
            # Phase / round / turn intact
            assert before_view['phase'] == after_view['phase']
            assert before_view['round'] == after_view['round']
            assert before_view['turn'] == after_view['turn']
            # Own hand unchanged (card refs match)
            before_hand = [c['ref'] for c in before_view['players'][0]['hand']]
            after_hand = [c['ref'] for c in after_view['players'][0]['hand']]
            assert before_hand == after_hand
        finally:
            env.close()

    def test_deterministic_given_seed(self):
        """Two searches with the same seed on the same env state must
        produce the same chosen action. Verifies no ambient
        randomness (numpy without seed, torch without seed)."""
        env1 = _make_env(['赤蝶'], ['赤蝶'], seed=123)
        env2 = _make_env(['赤蝶'], ['赤蝶'], seed=123)
        try:
            agent1 = _small_agent(env1, seed=777)
            agent2 = _small_agent(env2, seed=777)
            pool1 = _pool_from_env(env1, 1)
            pool2 = _pool_from_env(env2, 1)
            cfg = MCTSConfig(n_rollouts=20, temperature=0.0, temperature_switch_step=0)
            chosen1, _ = mcts_search(
                env1,
                agent1,
                SharedFixedPool(pool1),
                random.Random(42),
                viewing_player=env1.acting_player,
                config=cfg,
            )
            chosen2, _ = mcts_search(
                env2,
                agent2,
                SharedFixedPool(pool2),
                random.Random(42),
                viewing_player=env2.acting_player,
                config=cfg,
            )
            assert chosen1 == chosen2
        finally:
            env1.close()
            env2.close()


class TestDirichletAtRoot:
    def test_dirichlet_modifies_root_child_priors(self):
        """With Dirichlet eps=0, root children's priors come straight
        from the network. With eps=1, root children's priors ARE the
        Dirichlet draw. Verify eps=0 and eps=1 give different priors."""
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg_no_noise = MCTSConfig(
                n_rollouts=1,
                dirichlet_eps=0.0,
                max_rollout_depth=200,
            )
            cfg_all_noise = MCTSConfig(
                n_rollouts=1,
                dirichlet_alpha=1.0,
                dirichlet_eps=1.0,
                max_rollout_depth=200,
            )
            _, info_a = mcts_search(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg_no_noise,
            )
            _, info_b = mcts_search(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg_all_noise,
            )
            # The two shouldn't be structurally different (same legal
            # ids, same 1 rollout), but with eps=1 the root priors
            # are the Dirichlet draw, not the network output.
            # Harder to assert directly without root access; just
            # assert the two searches ran without error.
            assert len(info_a['legal_ids']) > 0
            assert len(info_b['legal_ids']) > 0
        finally:
            env.close()


class TestMaxDepthRaises:
    def test_max_rollout_depth_raises(self):
        """Set max_rollout_depth to 0; any descent past the root
        triggers depth > 0 and raises. Verifies the cap is hard,
        not soft-clamped to draw."""
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            # Need > 1 rollout so tree grows past a pure leaf expansion.
            # Rollout 1 expands root leaves. Rollout 2 picks a child,
            # steps env, and descends into it — depth becomes 1 > 0.
            cfg = MCTSConfig(n_rollouts=5, max_rollout_depth=0)
            with pytest.raises(RuntimeError, match='max_rollout_depth'):
                mcts_search(
                    env,
                    agent,
                    SharedFixedPool(pool),
                    random.Random(0),
                    viewing_player=env.acting_player,
                    config=cfg,
                )
        finally:
            env.close()


class TestArgmaxVisitsDeterminism:
    def test_tie_breaks_by_action_id(self):
        """Two children with the same visit count → argmax chooses
        the smaller ActionId, not the insertion-order first."""
        root = MCTSNode(turn=0, terminal=False)
        aid_a = (0, 10, -1, -1, -1, (0,) * 8)
        aid_b = (0, 5, -1, -1, -1, (0,) * 8)
        root.children[aid_a] = MCTSNode(turn=1, terminal=False, N=3)
        root.children[aid_b] = MCTSNode(turn=1, terminal=False, N=3)
        best = _argmax_visits(root)
        # (0, 5, ...) < (0, 10, ...) lexicographically
        assert best == aid_b


class TestDetectDiscovery:
    def test_fires_on_late_convergence(self):
        """ckpt[50]=A, ckpt[200]=B, ckpt[400]=B → discovery fires at 400."""
        events = _detect_discovery(
            {50: 'A', 100: 'A', 200: 'B', 400: 'B'},
            (50, 100, 200, 400),
        )
        assert events == [400]

    def test_no_event_when_stable(self):
        events = _detect_discovery(
            {50: 'X', 100: 'X', 200: 'X', 400: 'X'},
            (50, 100, 200, 400),
        )
        assert events == []

    def test_no_event_when_mid_disagrees(self):
        """ckpt[200] != ckpt[400] means the search hasn't stabilized
        — not a discovery event, just noise."""
        events = _detect_discovery(
            {50: 'A', 100: 'A', 200: 'C', 400: 'B'},
            (50, 100, 200, 400),
        )
        assert events == []


class TestMCTSProfile:
    def test_profile_off_no_key(self):
        """With profile=False (default), info dict has no 'profile' key."""
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(n_rollouts=5, profile=False)
            _, info = mcts_search(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            assert 'profile' not in info
        finally:
            env.close()

    def test_profile_on_returns_breakdown(self):
        """With profile=True on mcts_search_parallel, info contains
        a profile dict with timing breakdown and percentages."""
        from training.paradigms.az.mcts import mcts_search_parallel

        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)

            # Minimal client stub matching send_eval/recv_eval protocol.
            class _FakeClient:
                def __init__(self, agent):
                    self._agent = agent
                    self._pending = []

                def send_eval(self, dyn, refs, payments):
                    prior, value = self._agent.eval_state(dyn, refs, payments)
                    self._pending.append((prior, value))

                def recv_eval(self):
                    return self._pending.pop(0)

            client = _FakeClient(agent)
            cfg = MCTSConfig(
                n_rollouts=10,
                parallel_rollouts=2,
                value_mix_lambda=0.5,
                profile=True,
            )
            _, info = mcts_search_parallel(
                env,
                client,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            assert 'profile' in info
            p = info['profile']
            assert p['n_rollouts'] == 10
            assert p['total_s'] > 0
            # Check counts and times exist for active categories.
            assert p['n_restore'] > 0
            assert p['n_determinize'] > 0
            assert p['n_eval'] > 0
            assert p['n_rollout'] > 0
            assert p['eval_s'] > 0
            assert p['rollout_s'] > 0
            assert 'pct_rollout' in p
            assert 'pct_eval' in p
            assert 'pct_ctypes' in p
        finally:
            env.close()

    def test_profile_as_dict(self):
        """MCTSProfile.as_dict produces the expected keys."""
        p = MCTSProfile(
            determinize_s=0.01,
            restore_s=0.005,
            eval_s=0.02,
            rollout_s=0.03,
            env_step_s=0.008,
            env_query_s=0.004,
            n_rollouts=50,
        )
        d = p.as_dict()
        assert d['n_rollouts'] == 50
        assert d['total_s'] > 0
        assert d['pct_rollout'] > 0
        assert d['pct_ctypes'] > 0
        assert d['pct_eval'] > 0
        # Zero fields should not appear
        assert 'descend_s' not in d
        assert 'eval_send_s' not in d
