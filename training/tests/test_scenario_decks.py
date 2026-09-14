"""F4 deck_0/deck_1 cfg plumbing contract tests.

Covers: TOML → ScenarioCfg round-trip, [scenario] unknown-key strict
validation (typo'd deck field must not silently fall back to the
implicit path), ScenarioConfig char_pool × explicit-deck exclusion,
decks_arg conversion helper, run_matchup mode guard, and the DMC Go
game_spec carrying players[i].deck."""

from __future__ import annotations

from pathlib import Path

import pytest

from training.core.config.loader import load_cfg
from training.core.scenario import ScenarioConfig, decks_arg

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE_TOML = _REPO_ROOT / 'configs' / 'dmc' / 'smoke.toml'
_ANCHOR = 'card_pool = ["测试卡_增幅", "测试卡_碎片"]\n'


def _write_variant(tmp_path: Path, extra_scenario_lines: str) -> Path:
    """Copy dmc/smoke.toml with extra lines inserted into [scenario]."""
    text = _SMOKE_TOML.read_text(encoding='utf-8')
    assert text.count(_ANCHOR) == 1, 'smoke.toml [scenario] anchor drifted'
    out = tmp_path / 'variant.toml'
    out.write_text(text.replace(_ANCHOR, _ANCHOR + extra_scenario_lines), encoding='utf-8')
    return out


class TestLoaderRoundTrip:
    def test_deck_fields_round_trip(self, tmp_path):
        path = _write_variant(
            tmp_path,
            'deck_0 = ["测试卡_增幅", "测试卡_增幅", "测试卡_碎片"]\ndeck_1 = ["测试卡_碎片"]\n',
        )
        cfg = load_cfg(path)
        assert cfg.scenario.deck_0 == ['测试卡_增幅', '测试卡_增幅', '测试卡_碎片']
        assert cfg.scenario.deck_1 == ['测试卡_碎片']

    def test_deck_fields_default_none(self):
        cfg = load_cfg(_SMOKE_TOML)
        assert cfg.scenario.deck_0 is None
        assert cfg.scenario.deck_1 is None

    def test_unknown_scenario_key_raises(self, tmp_path):
        # Typo'd deck field would silently no-op back to the implicit
        # path without the strict check — must fail at load time.
        path = _write_variant(tmp_path, 'dekc_0 = ["测试卡_增幅"]\n')
        with pytest.raises(ValueError, match=r'unknown field in \[scenario\].*dekc_0'):
            load_cfg(path)


class TestScenarioConfigExclusion:
    def test_loader_scenario_cfg_path_raises(self, tmp_path):
        # ScenarioCfg (frozen, no __post_init__ validation) used to slip
        # past the char_pool × deck exclusion — the loader must enforce
        # it itself at [scenario] parse time.
        path = _write_variant(tmp_path, 'char_pool = ["赤蝶", "墨客"]\ndeck_0 = ["测试卡_增幅"]\n')
        with pytest.raises(ValueError, match='char_pool.*incompatible'):
            load_cfg(path)

    def test_dmc_eval_override_path_raises(self, tmp_path):
        # DMC eval load_config applies overrides via setattr, bypassing
        # ScenarioConfig.__post_init__ — must re-validate afterwards.
        from training.paradigms.dmc._run_config import load_config

        path = tmp_path / 'dmc_eval.toml'
        path.write_text(
            'base = "smoke"\n\n[scenario]\nchar_pool = ["赤蝶", "墨客"]\ndeck_0 = ["测试卡_增幅"]\n',
            encoding='utf-8',
        )
        with pytest.raises(ValueError, match='char_pool.*incompatible'):
            load_config(path)

    def test_char_pool_with_deck_raises(self):
        with pytest.raises(ValueError, match='char_pool.*incompatible'):
            ScenarioConfig(
                team_0=['赤蝶'],
                team_1=['墨客'],
                char_pool=['赤蝶', '墨客'],
                team_size=1,
                deck_0=['佛跳墙'],
            )

    def test_char_pool_without_deck_ok(self):
        sc = ScenarioConfig(team_0=['赤蝶'], team_1=['墨客'], char_pool=['赤蝶', '墨客'], team_size=1)
        assert sc.deck_0 is None and sc.deck_1 is None

    def test_fixed_teams_with_decks_ok(self):
        sc = ScenarioConfig(team_0=['赤蝶'], team_1=['墨客'], deck_0=['佛跳墙'], deck_1=['占星'])
        assert sc.deck_0 == ['佛跳墙']


class TestDecksArg:
    def test_both_none_collapses_to_none(self):
        assert decks_arg(None, None) is None

    def test_single_side(self):
        assert decks_arg(['佛跳墙'], None) == [['佛跳墙'], None]
        assert decks_arg(None, ['占星']) == [None, ['占星']]

    def test_copies_inputs(self):
        d0 = ['佛跳墙']
        out = decks_arg(d0, d0)
        out[0].append('占星')
        assert d0 == ['佛跳墙']


class TestRunMatchupGuard:
    def test_decks_require_fixed_mode(self):
        from training.core.matchup.matchup import run_matchup

        with pytest.raises(ValueError, match='explicit decks require mode=fixed'):
            run_matchup(
                [{'type': 'random'}, {'type': 'random'}],
                mode='enumerate_disjoint',
                char_pool=['赤蝶', '墨客'],
                team_size=1,
                decks=[['佛跳墙'], None],
            )


class TestGoGameSpecCarriesDeck:
    def test_game_spec_players_deck(self):
        """DMC Go-subprocess path assembles game_spec by hand — its
        players[i].deck must mirror [scenario].deck_0/deck_1, otherwise
        deck behavior forks across actor backends."""
        from types import SimpleNamespace

        from training.paradigms.dmc.paradigm import DMCParadigm

        sc = SimpleNamespace(
            pool=['v_legacy'],
            team_0=['赤蝶'],
            team_1=['墨客'],
            card_pool=['佛跳墙', '占星'],
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            max_rounds=15,
            deck_0=['佛跳墙'],
            deck_1=None,
        )
        players = []
        for team, deck in ((sc.team_0, sc.deck_0), (sc.team_1, sc.deck_1)):
            p = {'chars': [{'name': n} for n in team]}
            if deck is not None:
                p['deck'] = list(deck)
            players.append(p)
        # Source-level parity assertion: the builder logic above is the
        # exact game_spec assembly in DMCParadigm._make_go_collector —
        # verify the method body still contains the deck wiring (cheap
        # guard against the Go path silently dropping the field).
        import inspect

        src = inspect.getsource(DMCParadigm._make_go_collector)
        assert "p['deck'] = list(deck)" in src, 'Go game_spec no longer wires players[i].deck'
        assert players[0]['deck'] == ['佛跳墙']
        assert 'deck' not in players[1]
