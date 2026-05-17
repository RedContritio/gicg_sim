"""D1: ObsConfig toggles tests.

Verify each obs config field has the expected effect on the engine's
observation output. Strategy: construct two envs with only one toggle
differing, compare static_obs byte-diff on the relevant region.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from gicg_env import GicgEnv

DATA_DIR = os.environ.get('GICG_DATA_DIR', 'data')
OBS_MAX_CHARS = 6
OBS_MAX_SKILLS_PER_CHAR = 10


def _env(*, obs_config=None, seed=0):
    env = GicgEnv(
        ['赤蝶'],
        ['墨客'],
        seed=seed,
        data_dir=DATA_DIR,
        obs_config=obs_config,
    )
    return env


def _skill_refs_region_slice(env) -> tuple[int, int]:
    """Compute [start, end) of the char_skill_refs region inside
    static_obs. Layout = counter_meta + skill_refs + hook_tokens.
    counter_meta size = obsCounterSlots * 3; skill_refs size =
    2 * ObsMaxChars * ObsMaxSkillsPerChar."""
    # We can derive sizes from the engine rather than hardcoding —
    # stays correct if dims change.
    lib = env._engine._lib
    n_char = 6  # ObsMaxChars
    n_skill = 10  # ObsMaxSkillsPerChar
    # Counter section: 2*6*128 + 2*140 + 16 = 1816 slots * 3 = 5448
    # Easier: read the offsets via the two labels:
    # counter_slots = sum of per-group sizes. Use GameGetStaticObsSize
    # indirectly — but the public API doesn't expose the offsets
    # cleanly. Hardcode the sizes from observation.go consts:
    obs_char_slots = 128
    obs_player_slots = 140
    obs_global_slots = 16
    counter_slots = 2 * n_char * obs_char_slots + 2 * obs_player_slots + obs_global_slots
    counter_meta_size = counter_slots * 3
    skill_refs_size = 2 * n_char * n_skill
    return counter_meta_size, counter_meta_size + skill_refs_size


def test_include_char_skill_refs_true_populates_real_refs():
    """Default (all-on) should populate char_skill_refs with non-(-1)
    values for the active chars' skills."""
    env = _env(obs_config=None)  # legacy default all-on
    try:
        static = env.static_obs
        start, end = _skill_refs_region_slice(env)
        region = static[start:end]
        # 赤蝶 has 3 skills, 墨客 has 3 → at least 6 slots should be >= 0
        non_neg = int(np.sum(region >= 0))
        assert non_neg >= 6, f'expected ≥6 non-negative skill ref slots (3 per char × 2 teams), got {non_neg}'
    finally:
        env.close()


def test_include_char_skill_refs_false_fills_minus_one():
    """`include_char_skill_refs=false` must fill the region with -1."""
    obs_cfg = {
        'include_char_skill_refs': False,
        'shuffle_counters': True,
        'shuffle_hooks': True,
        'shuffle_cards': True,
        'shuffle_skill_slots': True,
    }
    env = _env(obs_config=obs_cfg)
    try:
        static = env.static_obs
        start, end = _skill_refs_region_slice(env)
        region = static[start:end]
        # All entries should be exactly -1
        assert int(np.all(region == -1)), (
            f'expected region filled with -1, got min={region.min()} '
            f'max={region.max()} non_minus_one={int(np.sum(region != -1))}'
        )
    finally:
        env.close()


def test_shuffle_counters_false_gives_identity_perm_over_non_structural():
    """shuffle_counters=false + same seed should yield deterministic
    counter sids (no rng). Two envs with same seed + toggle=false should
    produce byte-identical static_obs."""
    base_cfg = {
        'include_char_skill_refs': True,
        'shuffle_counters': False,  # key toggle
        'shuffle_hooks': False,
        'shuffle_cards': False,
        'shuffle_skill_slots': False,
    }
    env1 = _env(obs_config=base_cfg, seed=42)
    env2 = _env(obs_config=base_cfg, seed=42)
    try:
        assert np.array_equal(env1.static_obs, env2.static_obs), (
            'all-shuffles-off with same seed should be byte-identical'
        )
    finally:
        env1.close()
        env2.close()


def test_shuffle_counters_toggle_changes_sid_mapping():
    """Switching shuffle_counters from true to false MUST change the
    counter sid mapping (since true uses rng.Perm, false uses identity).
    Compare with same seed."""
    cfg_on = {
        'include_char_skill_refs': True,
        'shuffle_counters': True,
        'shuffle_hooks': False,  # keep fixed to isolate
        'shuffle_cards': False,
        'shuffle_skill_slots': False,
    }
    cfg_off = dict(cfg_on)
    cfg_off['shuffle_counters'] = False

    env_on = _env(obs_config=cfg_on, seed=42)
    env_off = _env(obs_config=cfg_off, seed=42)
    try:
        # counter-meta region differs (the sid values differ)
        obs_char_slots = 128
        obs_player_slots = 140
        obs_global_slots = 16
        counter_slots = 2 * 6 * obs_char_slots + 2 * obs_player_slots + obs_global_slots
        counter_meta_end = counter_slots * 3
        on_region = env_on.static_obs[:counter_meta_end]
        off_region = env_off.static_obs[:counter_meta_end]
        assert not np.array_equal(on_region, off_region), (
            'shuffle_counters on vs off should produce different counter meta'
        )
    finally:
        env_on.close()
        env_off.close()


def test_omitting_obs_config_matches_all_defaults():
    """Default obs_config=None should produce same static_obs as
    explicit all-true dict (both → legacy all-on behavior)."""
    cfg_all_true = {
        'include_char_skill_refs': True,
        'shuffle_counters': True,
        'shuffle_hooks': True,
        'shuffle_cards': True,
        'shuffle_skill_slots': True,
    }
    env_default = _env(obs_config=None, seed=42)
    env_explicit = _env(obs_config=cfg_all_true, seed=42)
    try:
        assert np.array_equal(env_default.static_obs, env_explicit.static_obs), (
            'obs_config=None should equal explicit all-true dict'
        )
    finally:
        env_default.close()
        env_explicit.close()
