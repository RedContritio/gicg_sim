"""Tests for GicgEnv state inspection / hidden-state injection / replay.

Split out of ``test_env.py`` to keep each test module focused.
Covers:
  - TestSetHiddenState: set_player_hand/deck/dice — the IS-MCTS
    determinization injection API
  - TestExportView: export_view() contract (web UI consumer)
  - TestReplayTo: replay_to + record_extract_info rewind path
"""

import os
import pytest

from gicg_env import GicgEnv
from gicg_env.tests._helpers import keep_all_rerolls

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def make_env(team_0, team_1, **kw):
    # Default to a multi-pool union so tests that exercise legacy
    # replays (e.g. 赤蝶_vs_墨客.yaml referencing 测试卡_碎片) keep
    # working post ADR-0011's prod/test pool split. Caller can still
    # override pool=... in **kw to test a single pool.
    kw.setdefault('pool', ['v_legacy', 'test_basic'])
    return GicgEnv(team_0, team_1, data_dir=DATA_DIR, **kw)


class TestSetHiddenState:
    """Tests for set_player_hand / set_player_deck — the IS-MCTS
    determinization injection API. See
    ``docs/2_decisions/adr-0005-az_decisions_d1_d14.md``."""

    def test_set_player_hand_replaces_content(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            keep_all_rerolls(env)
            view_before = env.export_view()
            p0_hand_before = view_before['players'][0]['hand']
            assert len(p0_hand_before) > 0, 'expected non-empty initial hand'
            any_ref = p0_hand_before[0]['ref']

            env.set_player_hand(0, [any_ref, any_ref, any_ref])

            view_after = env.export_view()
            assert len(view_after['players'][0]['hand']) == 3
            for card in view_after['players'][0]['hand']:
                assert card['ref'] == any_ref

    def test_set_player_hand_preserves_other_state(self):
        """Verify set_player_hand doesn't disturb HP, deck, discard,
        or the other player's hand."""
        with make_env(['赤蝶', '墨客'], ['猫咪', '刻师傅']) as env:
            env.reset()
            keep_all_rerolls(env)
            view_before = env.export_view()
            p0_hp = [c['hp'] for c in view_before['players'][0]['chars']]
            p1_hp = [c['hp'] for c in view_before['players'][1]['chars']]
            p1_hand_before = view_before['players'][1]['hand']
            p0_deck_count = view_before['players'][0]['deck_count']

            ref = p1_hand_before[0]['ref']
            env.set_player_hand(0, [ref])

            view_after = env.export_view()
            assert [c['hp'] for c in view_after['players'][0]['chars']] == p0_hp
            assert [c['hp'] for c in view_after['players'][1]['chars']] == p1_hp
            assert view_after['players'][0]['deck_count'] == p0_deck_count
            assert view_after['players'][1]['hand'] == p1_hand_before

    def test_set_player_hand_rejects_bad_player(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            with pytest.raises(ValueError, match='player must be 0 or 1'):
                env.set_player_hand(2, [])
            with pytest.raises(ValueError, match='player must be 0 or 1'):
                env.set_player_hand(-1, [])

    def test_set_player_deck_rejects_bad_player(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            with pytest.raises(ValueError, match='player must be 0 or 1'):
                env.set_player_deck(99, [])

    def test_set_player_dice_rejects_bad_player(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            with pytest.raises(ValueError, match='player must be 0 or 1'):
                env.set_player_dice(2, [0] * 8)

    def test_set_player_dice_rejects_wrong_length(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            with pytest.raises(ValueError, match='expects 8 counts'):
                env.set_player_dice(0, [1, 2, 3])

    def test_set_player_dice_rejects_negative(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            with pytest.raises(ValueError, match='is negative'):
                env.set_player_dice(0, [-1, 0, 0, 0, 0, 0, 0, 0])

    def test_set_player_hand_empty_clears(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            env.set_player_hand(0, [])
            view = env.export_view()
            # Go's json marshal emits nil slice as null; both None and
            # [] mean "empty hand" from the Python side
            hand = view['players'][0]['hand']
            assert hand is None or len(hand) == 0

    def test_set_player_deck_replaces_content(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            keep_all_rerolls(env)
            # Grab a ref from existing state to use as injection content
            view = env.export_view()
            ref = view['players'][0]['hand'][0]['ref']

            env.set_player_deck(0, [ref, ref, ref, ref, ref])
            view_after = env.export_view()
            assert view_after['players'][0]['deck_count'] == 5

    def test_set_hidden_state_survives_snapshot_restore(self):
        """The canonical determinization pattern: snapshot the root,
        inject hidden state, roll forward, restore. Verify the injected
        state is visible between restore and snapshot_free."""
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            keep_all_rerolls(env)
            snap = env.snapshot()
            try:
                view_before = env.export_view()
                ref = view_before['players'][0]['hand'][0]['ref']

                env.set_player_hand(0, [ref, ref])
                view_injected = env.export_view()
                assert len(view_injected['players'][0]['hand']) == 2

                env.restore(snap)
                view_restored = env.export_view()
                assert len(view_restored['players'][0]['hand']) == len(view_before['players'][0]['hand'])
            finally:
                env.snapshot_free(snap)


class TestExportView:
    """export_view() contract tests — this is what the web UI consumes."""

    def test_initial_state_shape(self):
        with make_env(['赤蝶', '墨客'], ['猫咪', '刻师傅']) as env:
            env.reset()
            view = env.export_view()
            assert view['phase'] in ('select_active', 'action', 'round_start')
            assert view['round'] >= 1
            assert view['winner'] == -1
            assert len(view['players']) == 2

            p0_chars = view['players'][0]['chars']
            assert len(p0_chars) == 2
            assert p0_chars[0]['name'] == '赤蝶'
            assert p0_chars[1]['name'] == '墨客'

            known_elements = {
                'none',
                'fire',
                'ice',
                'water',
                'electro',
                'geo',
                'anemo',
                'dendro',
                'physical',
            }
            for pi in range(2):
                for cv in view['players'][pi]['chars']:
                    assert cv['alive'] is True
                    assert 0 < cv['hp'] <= cv['hp_max']
                    assert cv['hp_max'] > 0
                    assert isinstance(cv['element'], str)
                    assert cv['element'] in known_elements

    def test_hand_names_populated(self):
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            keep_all_rerolls(env)
            view = env.export_view()
            for pi in range(2):
                for card in view['players'][pi]['hand']:
                    assert isinstance(card['name'], str)
                    assert len(card['name']) > 0

    def test_reflects_live_changes(self):
        """Play one step and verify the view actually updated."""
        with make_env(['赤蝶'], ['墨客']) as env:
            env.reset()
            keep_all_rerolls(env)
            env.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 8])
            before = env.export_view()
            kinds, _ = env.get_legal_actions()
            if len(kinds) > 0:
                env.step(0)
            after = env.export_view()
            changed = (
                before['turn'] != after['turn']
                or before['players'][0]['chars'][0]['hp'] != after['players'][0]['chars'][0]['hp']
                or before['players'][0]['deck_count'] != after['players'][0]['deck_count']
            )
            assert changed, "view didn't change after a step"


@pytest.fixture(scope='module')
def replay_yaml(tmp_path_factory):
    """Generate a deterministic replay yaml for TestReplayTo via
    random_rollout + export_replay. Self-contained: no dependency on
    the gitignored artifacts/ tree. Pool / teams match TestReplayTo
    expectations (`['赤蝶'] vs ['墨客']`, make_env default pool).
    seed=42 → completes in ~22 record-level steps across 4 rounds."""
    tmp_dir = tmp_path_factory.mktemp('replay_fixture')
    yaml_path = tmp_dir / 'replay.yaml'
    with make_env(['赤蝶'], ['墨客']) as env:
        env.reset(seed=42)
        winner, _ = env._engine.random_rollout(seed=42, max_steps=500)
        assert winner in (0, 1), f'replay fixture: rollout did not terminate (winner={winner})'
        yaml_path.write_text(env.export_replay(), encoding='utf-8')
    return str(yaml_path)


class TestReplayTo:
    """replay_to + record_extract_info — the web backend's rewind path."""

    def test_extract_info(self, replay_yaml):
        from gicg_env.engine import record_extract_info

        info = record_extract_info(replay_yaml)
        assert 'teams' in info
        assert len(info['teams']) == 2
        assert info['teams'][0] == ['赤蝶']
        assert info['teams'][1] == ['墨客']
        assert info['total_steps'] > 0
        assert info['rounds'] >= 1

    def test_replay_to_step_zero(self, replay_yaml):
        """step=0 = immediately after Load, before any round_start hook
        has fired in this freshly-constructed env. round_num may report
        0 ('about to begin round 1') rather than 1 — acceptable."""
        from gicg_env.engine import record_extract_info

        info = record_extract_info(replay_yaml)
        with make_env(info['teams'][0], info['teams'][1]) as env:
            result = env.replay_to(replay_yaml, 0)
            assert result['step'] == 0
            assert result['total_steps'] == info['total_steps']
            view = result['view']
            assert view['round'] >= 0
            assert view['winner'] == -1

    def test_replay_to_terminal(self, replay_yaml):
        """Rewinding to the final step must land on game-over."""
        from gicg_env.engine import record_extract_info

        info = record_extract_info(replay_yaml)
        with make_env(info['teams'][0], info['teams'][1]) as env:
            result = env.replay_to(replay_yaml, info['total_steps'])
            view = result['view']
            assert view['winner'] in (0, 1), f'winner={view["winner"]}'

    def test_replay_to_mid(self, replay_yaml):
        """Halfway rewind should produce a view with bounded HP and a
        non-negative round index — a soft invariant check that state
        reconstruction didn't silently break."""
        from gicg_env.engine import record_extract_info

        info = record_extract_info(replay_yaml)
        mid = info['total_steps'] // 2
        with make_env(info['teams'][0], info['teams'][1]) as env:
            result = env.replay_to(replay_yaml, mid)
            assert result['step'] == mid
            view = result['view']
            assert view['round'] >= 1
            for pv in view['players']:
                for cv in pv['chars']:
                    assert 0 <= cv['hp'] <= cv['hp_max']
