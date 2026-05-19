"""Tests for cfg-toml-restructure-paradigm-scoped N6 — hybrid TOML structure.

Verifies the `load_paradigm_cfg(toml_dict, paradigm_name) -> dict` helper +
end-to-end `load_cfg` against 10 hybrid toml configs (5 paradigm × 2 preset).

Spec ref: config-schema/spec.md § 8 N6 (hybrid TOML structure).

Covered invariants:
- N6.1 / CC-301: legacy flat [paradigm].scalar → raise
- N6.2: dispatch via meta.paradigm, paradigm-scoped section extracted
- N6.3 / CC-304: non-dispatched [paradigm.<wrong>] silent ignored
- N6.4 / CC-305: [shape] optional, missing → factory default
- N6.4 / CC-303: [shape] + [paradigm.X.agent] dict merge, agent overrides
- N6.5 / CC-306: load_paradigm_cfg shared helper from core.cfg
- N6.6: ALLOWED_TOP_LEVEL contains 'shape'
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from training.core.cfg import load_paradigm_cfg
from training.core.config.loader import load_cfg


# ---------- N6.1 / CC-301: legacy flat raise ---------- #


def test_load_paradigm_cfg_legacy_flat_scalar_raises():
    """Legacy form [paradigm].lr=... (scalar) raises pointing to hybrid."""
    toml_dict = {'paradigm': {'lr': 1e-3, 'batch_size': 32}}
    with pytest.raises(ValueError, match='legacy flat'):
        load_paradigm_cfg(toml_dict, 'az')


def test_load_paradigm_cfg_legacy_mixed_scalar_raises():
    """Mixed scalar + nested still raises (any scalar under [paradigm] = legacy)."""
    toml_dict = {
        'paradigm': {
            'lr': 1e-3,  # legacy scalar
            'az': {'batch_size': 32},  # hybrid nested
        }
    }
    with pytest.raises(ValueError, match='legacy flat'):
        load_paradigm_cfg(toml_dict, 'az')


# ---------- N6.2: dispatch extraction ---------- #


def test_load_paradigm_cfg_extracts_dispatched_section():
    """[paradigm.az] extracted as flat top-level for from_dict()."""
    toml_dict = {
        'paradigm': {
            'az': {
                'lr': 1e-3,
                'batch_size': 64,
                'mcts': {'n_rollouts': 100},
            }
        }
    }
    flat = load_paradigm_cfg(toml_dict, 'az')
    assert flat['lr'] == 1e-3
    assert flat['batch_size'] == 64
    assert flat['mcts'] == {'n_rollouts': 100}


def test_load_paradigm_cfg_missing_paradigm_section_returns_empty():
    """Missing [paradigm.<name>] → empty dict (paradigm uses all defaults)."""
    toml_dict = {'paradigm': {}}
    flat = load_paradigm_cfg(toml_dict, 'az')
    assert flat == {}


def test_load_paradigm_cfg_missing_paradigm_root_returns_empty():
    """Missing [paradigm] entirely → empty dict."""
    toml_dict = {}
    flat = load_paradigm_cfg(toml_dict, 'az')
    assert flat == {}


# ---------- N6.3 / CC-304: non-dispatched sections silent ignored ---------- #


def test_load_paradigm_cfg_other_paradigm_sections_ignored():
    """Non-dispatched [paradigm.<other>] silently ignored."""
    toml_dict = {
        'paradigm': {
            'ppo': {'gamma': 0.99},  # dispatched
            'az': {'lr': 1e-3},  # ignored
            'bc': {'n_epochs': 60},  # ignored
        }
    }
    flat = load_paradigm_cfg(toml_dict, 'ppo')
    assert flat == {'gamma': 0.99}
    # az / bc keys not leaked
    assert 'lr' not in flat
    assert 'n_epochs' not in flat


# ---------- N6.4 / CC-305: [shape] optional ---------- #


def test_load_paradigm_cfg_no_shape_section():
    """Missing [shape] → flat dict has no 'agent' key (paradigm factory default)."""
    toml_dict = {'paradigm': {'az': {'lr': 1e-3}}}
    flat = load_paradigm_cfg(toml_dict, 'az')
    assert 'agent' not in flat
    assert flat == {'lr': 1e-3}


def test_load_paradigm_cfg_shape_only_no_agent_override():
    """[shape] present + [paradigm.X.agent] absent → agent = shape verbatim."""
    toml_dict = {
        'shape': {'d_model': 128, 'n_cross_layers': 2},
        'paradigm': {'az': {'lr': 1e-3}},
    }
    flat = load_paradigm_cfg(toml_dict, 'az')
    assert flat['agent'] == {'d_model': 128, 'n_cross_layers': 2}
    assert flat['lr'] == 1e-3


# ---------- N6.4 / CC-303: [shape] + agent dict merge ---------- #


def test_load_paradigm_cfg_agent_overrides_shape_per_field():
    """[paradigm.X.agent] values override [shape] per-field."""
    toml_dict = {
        'shape': {'d_model': 128, 'n_cross_layers': 2, 'dropout': 0.0},
        'paradigm': {
            'ppo': {
                'agent': {'d_model': 256},  # override d_model only
            }
        },
    }
    flat = load_paradigm_cfg(toml_dict, 'ppo')
    assert flat['agent']['d_model'] == 256, 'agent override should win'
    assert flat['agent']['n_cross_layers'] == 2, 'shape value retained when not overridden'
    assert flat['agent']['dropout'] == 0.0


def test_load_paradigm_cfg_agent_full_override_shape():
    """[paradigm.X.agent] full override replaces [shape] field-for-field."""
    toml_dict = {
        'shape': {'d_model': 128, 'n_cross_layers': 2},
        'paradigm': {
            'bc': {
                'agent': {'d_model': 32, 'n_cross_layers': 1},
            }
        },
    }
    flat = load_paradigm_cfg(toml_dict, 'bc')
    assert flat['agent'] == {'d_model': 32, 'n_cross_layers': 1}


# ---------- Error semantics ---------- #


def test_load_paradigm_cfg_shape_not_section_raises():
    """[shape] must be a section (table), not scalar."""
    toml_dict = {'shape': 'not a dict', 'paradigm': {'az': {}}}
    with pytest.raises(ValueError, match=r'\[shape\] must be a section'):
        load_paradigm_cfg(toml_dict, 'az')


def test_load_paradigm_cfg_agent_not_section_raises():
    """[paradigm.X.agent] must be a section, not scalar."""
    toml_dict = {
        'shape': {'d_model': 128},
        'paradigm': {'az': {'agent': 'not a dict'}},
    }
    with pytest.raises(ValueError, match=r'agent\] must be a section'):
        load_paradigm_cfg(toml_dict, 'az')


def test_load_paradigm_cfg_paradigm_root_not_section_raises():
    """[paradigm] must be a section, not scalar."""
    toml_dict = {'paradigm': 'not a dict'}
    with pytest.raises(ValueError, match=r'\[paradigm\] must be a section'):
        load_paradigm_cfg(toml_dict, 'az')


def test_load_paradigm_cfg_paradigm_named_section_not_dict_raises():
    """[paradigm.<name>] must be a section."""
    toml_dict = {'paradigm': {'az': 'not a dict'}}
    with pytest.raises(ValueError, match=r'\[paradigm.az\] must be a section'):
        load_paradigm_cfg(toml_dict, 'az')


# ---------- N6.5 / CC-306: shared helper importable from core.cfg ---------- #


def test_load_paradigm_cfg_importable_from_core_cfg():
    """`load_paradigm_cfg` is exported from `training.core.cfg.__init__`."""
    from training.core.cfg import load_paradigm_cfg as imported

    assert imported is load_paradigm_cfg


# ---------- End-to-end: 10 cfg toml load (5 paradigm × 2 preset) ---------- #


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOML_PATHS = [
    _REPO_ROOT / 'configs' / paradigm / preset
    for paradigm in ('az', 'bc', 'cfr', 'dmc', 'ppo')
    for preset in ('default.toml', 'smoke.toml')
]


@pytest.mark.parametrize('toml_path', _TOML_PATHS, ids=lambda p: f'{p.parent.name}/{p.name}')
def test_load_cfg_hybrid_toml_loads(toml_path):
    """10 hybrid toml files (5 paradigm × 2 preset) all load via load_cfg without raise."""
    assert toml_path.exists(), f'cfg missing: {toml_path}'
    cfg = load_cfg(toml_path)
    # Sanity: meta.paradigm matches directory name (e.g. configs/az/* → meta.paradigm='az')
    assert cfg.meta.paradigm == toml_path.parent.name
    # paradigm dict was extracted via load_paradigm_cfg (hybrid structure)
    assert isinstance(cfg.paradigm, dict)


# ---------- End-to-end: shape + agent override semantics via load_cfg ---------- #


def test_load_cfg_ppo_default_d_model_override(tmp_path):
    """PPO default: [shape].d_model=128 + [paradigm.ppo.agent].d_model=256 → effective 256."""
    cfg = load_cfg(_REPO_ROOT / 'configs' / 'ppo' / 'default.toml')
    # paradigm dict's agent sub-dict carries the merged effective shape
    assert cfg.paradigm['agent']['d_model'] == 256, 'PPO default should override [shape] d_model 128 → 256'
    assert cfg.paradigm['agent']['n_cross_layers'] == 2, '[shape] n_cross_layers inherited'


# ---------- End-to-end: legacy flat detection via load_cfg ---------- #


def test_load_cfg_legacy_flat_toml_raises(tmp_path):
    """End-to-end: write a legacy flat [paradigm] toml → load_cfg raises."""
    legacy_toml = tmp_path / 'legacy_flat.toml'
    legacy_toml.write_text(
        textwrap.dedent("""\
            [meta]
            seed = 42
            paradigm = "az"
            run_label = "legacy_test"
            device = "cpu"

            [pipeline]
            mode = "serial"

            [scenario]
            team_0 = ["X"]
            team_1 = ["Y"]

            [paradigm]
            lr = 1e-3
            batch_size = 32
            """)
    )
    with pytest.raises(ValueError, match='legacy flat'):
        load_cfg(legacy_toml)


# ---------- N6.6: ALLOWED_TOP_LEVEL contains 'shape' ---------- #


def test_allowed_top_level_contains_shape():
    """schema.ALLOWED_TOP_LEVEL contains 'shape' (N6.6)."""
    from training.core.config.schema import ALLOWED_TOP_LEVEL

    assert 'shape' in ALLOWED_TOP_LEVEL


# ---------- Round-trip: hybrid load matches direct from_dict ---------- #


def test_round_trip_az_hybrid_matches_direct_from_dict():
    """Hybrid loader output → from_dict yields same cfg as direct from_dict call."""
    from training.paradigms.az.config import AZParadigmConfig

    toml_dict = {
        'shape': {'d_model': 64, 'n_cross_layers': 1, 'dropout': 0.1},
        'paradigm': {
            'az': {
                'version': '1.0.0',
                'paradigm': 'az',
                'lr': 5e-4,
                'mcts': {'n_rollouts': 50},
            }
        },
    }
    flat = load_paradigm_cfg(toml_dict, 'az')
    cfg_from_hybrid = AZParadigmConfig.from_dict(flat)

    # Direct from_dict — same fields manually arranged
    cfg_direct = AZParadigmConfig.from_dict(
        {
            'version': '1.0.0',
            'paradigm': 'az',
            'lr': 5e-4,
            'agent': {'d_model': 64, 'n_cross_layers': 1, 'dropout': 0.1},
            'mcts': {'n_rollouts': 50},
        }
    )
    assert cfg_from_hybrid == cfg_direct


def test_round_trip_ppo_hybrid_matches_direct_from_dict():
    """PPO hybrid → from_dict matches direct from_dict."""
    from training.paradigms.ppo.config import PPOParadigmConfig

    toml_dict = {
        'shape': {
            'n_counter_slots': 1832,
            'n_hooks': 900,
            'max_ops_per_hook': 120,
            'max_actions': 2048,
            'd_model': 128,
            'n_cross_layers': 2,
            'dropout': 0.0,
        },
        'paradigm': {
            'ppo': {
                'gamma': 0.99,
                'agent': {'d_model': 256},
            }
        },
    }
    flat = load_paradigm_cfg(toml_dict, 'ppo')
    cfg_from_hybrid = PPOParadigmConfig.from_dict(flat)

    cfg_direct = PPOParadigmConfig.from_dict(
        {
            'gamma': 0.99,
            'agent': {
                'n_counter_slots': 1832,
                'n_hooks': 900,
                'max_ops_per_hook': 120,
                'max_actions': 2048,
                'd_model': 256,  # agent override
                'n_cross_layers': 2,
                'dropout': 0.0,
            },
        }
    )
    assert cfg_from_hybrid == cfg_direct


# ---------- All 5 paradigm dispatch round-trip via load_paradigm_cfg ---------- #


@pytest.mark.parametrize('paradigm_name', ['az', 'bc', 'cfr', 'dmc', 'ppo'])
def test_load_paradigm_cfg_5_paradigm_dispatch(paradigm_name):
    """5 paradigm dispatch: same multi-paradigm toml → each extracts own section."""
    toml_dict = {
        'paradigm': {
            'az': {'lr': 1e-3},
            'bc': {'n_epochs': 60},
            'cfr': {'n_iterations': 100},
            'dmc': {'epsilon': 0.05},
            'ppo': {'gamma': 0.99},
        }
    }
    flat = load_paradigm_cfg(toml_dict, paradigm_name)
    expected = {
        'az': {'lr': 1e-3},
        'bc': {'n_epochs': 60},
        'cfr': {'n_iterations': 100},
        'dmc': {'epsilon': 0.05},
        'ppo': {'gamma': 0.99},
    }[paradigm_name]
    assert flat == expected
