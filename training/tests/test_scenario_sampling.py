"""ScenarioConfig.sample_teams unit tests.

Covers:
- fixed mode (char_pool=None) returns the configured teams unchanged
- random mode samples team_size from char_pool (mirror sampling allowed —
  #152 mirror bug resolved 2026-04-XX, no need to exclude mirror)
- disjoint_teams=True forces non-overlapping teams (covers former
  allow_mirror=False semantics + cross-team overlap exclusion)
- raises on team_size > pool size
- reproducibility: same rng seed → same sample
"""

from __future__ import annotations

import random

import pytest

from training.core.scenario import ScenarioConfig


def _scn(**kw):
    base = dict(team_0=['赤蝶'], team_1=['墨客'])
    base.update(kw)
    return ScenarioConfig(**base)


def test_fixed_mode_returns_configured_teams():
    s = _scn()
    rng = random.Random(0)
    t0, t1 = s.sample_teams(rng)
    assert t0 == ['赤蝶']
    assert t1 == ['墨客']
    # mutating returned lists must not affect the config
    t0.append('猫咪')
    assert s.team_0 == ['赤蝶']


def test_random_mode_samples_from_pool():
    pool = ['赤蝶', '墨客', '猫咪', '刻师傅', '天星']
    s = _scn(char_pool=pool, team_size=1)
    rng = random.Random(42)
    t0, t1 = s.sample_teams(rng)
    assert len(t0) == 1
    assert len(t1) == 1
    assert t0[0] in pool
    assert t1[0] in pool


def test_random_mode_team_size_2_internally_unique():
    """Each sampled team has no duplicate chars (rng.sample without
    replacement). Cross-team overlap is allowed by default."""
    pool = ['A', 'B', 'C', 'D', 'E']
    s = _scn(
        team_0=['A', 'B'],
        team_1=['B', 'C'],  # cross-team overlap OK
        char_pool=pool,
        team_size=2,
    )
    rng = random.Random(0)
    for _ in range(50):
        t0, t1 = s.sample_teams(rng)
        assert len(set(t0)) == len(t0), f'team_0 has dup: {t0}'
        assert len(set(t1)) == len(t1), f'team_1 has dup: {t1}'


def test_internal_dup_in_eval_team_raises():
    """Eval team_0 = ['A', 'A'] is rejected at construction."""
    with pytest.raises(ValueError, match='duplicate'):
        _scn(team_0=['A', 'A'], team_1=['B', 'C'], char_pool=['A', 'B', 'C'], team_size=2)


def test_eval_team_size_mismatch_raises():
    """Eval team_0 size ≠ training team_size raises."""
    with pytest.raises(ValueError, match='team_size'):
        _scn(team_0=['A'], team_1=['B'], char_pool=['A', 'B', 'C'], team_size=2)


def test_random_mode_allows_mirror():
    """Mirror matchups are valid sampling outcomes (#152 mirror bug
    resolved). Single-char pool always produces mirror; multi-char pool
    occasionally produces mirror."""
    pool = ['A']
    s = _scn(team_0=['A'], team_1=['A'], char_pool=pool, team_size=1)
    rng = random.Random(0)
    t0, t1 = s.sample_teams(rng)
    assert t0 == ['A']
    assert t1 == ['A']


def test_team_size_too_big_raises():
    # team_0/team_1 must satisfy size constraint first; then sampling
    # raises because team_size > pool size.
    with pytest.raises(ValueError):
        _scn(team_0=['A', 'B'], team_1=['A', 'B'], char_pool=['A'], team_size=2)


def test_reproducible_with_same_seed():
    pool = ['A', 'B', 'C', 'D', 'E']
    s = _scn(
        team_0=['A', 'B'],
        team_1=['C', 'D'],
        char_pool=pool,
        team_size=2,
    )
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    seq1 = [s.sample_teams(rng1) for _ in range(5)]
    seq2 = [s.sample_teams(rng2) for _ in range(5)]
    assert seq1 == seq2


def test_disjoint_teams_produces_no_overlap():
    """disjoint_teams=True guarantees team_1 shares no char with team_0.
    Needed for team_size>=2 to dodge issue #152 (char buff files load
    per-binding; same char on both teams registers its hooks twice)."""
    pool = ['A', 'B', 'C', 'D', 'E']
    s = _scn(
        team_0=['A', 'B'],
        team_1=['C', 'D'],
        char_pool=pool,
        team_size=2,
        disjoint_teams=True,
    )
    rng = random.Random(0)
    for _ in range(100):
        t0, t1 = s.sample_teams(rng)
        overlap = set(t0) & set(t1)
        assert not overlap, f'disjoint violated: {t0} vs {t1}'


def test_disjoint_teams_raises_when_pool_too_small():
    """char_pool needs >= 2*team_size distinct chars when disjoint_teams
    is set."""
    pool = ['A', 'B', 'C']  # only 3 chars, team_size=2 → 2 need + 2 need = 4
    s = _scn(
        team_0=['A', 'B'],
        team_1=['B', 'C'],
        char_pool=pool,
        team_size=2,
        disjoint_teams=True,
    )
    with pytest.raises(ValueError, match='disjoint_teams'):
        s.sample_teams(random.Random(0))


def test_disjoint_teams_works_for_team_size_1():
    """team_size=1 + disjoint_teams excludes mirror (since mirror is the
    only overlap pattern at team_size=1)."""
    pool = ['A', 'B', 'C']
    s = _scn(
        team_0=['A'],
        team_1=['B'],
        char_pool=pool,
        team_size=1,
        disjoint_teams=True,
    )
    rng = random.Random(0)
    for _ in range(50):
        t0, t1 = s.sample_teams(rng)
        assert t0[0] != t1[0], f'disjoint violated: {t0} vs {t1}'


def test_curriculum_env_knobs_default():
    """max_rounds + fix_dice + obs_mask default to legacy values
    (unbounded / random roll / fully observable). Stage 0 / 1 / 2 spec
    overrides these via TOML."""
    s = _scn()
    assert s.max_rounds == 0
    assert s.fix_dice is None
    assert s.obs_mask is None


def test_curriculum_env_knobs_forwarded_to_env():
    """ScenarioConfig.{max_rounds,fix_dice,obs_mask} must reach GicgEnv
    via env_factory — Stage 0/1/2 spec relies on this."""
    import os
    from types import SimpleNamespace

    from training.core.env_factory import make_env_factory
    from training.core.scenario import ObsConfig

    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    scenario = ScenarioConfig(
        team_0=['赤蝶'],
        team_1=['赤蝶'],
        card_pool=[],
        data_dir=data_dir,
        max_rounds=3,
        fix_dice=[2, 2, 2, 2, 0, 0, 0, 0],
        obs_mask=['enemy_dice'],
    )
    # make_env_factory reads only cfg.scenario (paradigm-agnostic) — a
    # SimpleNamespace stub suffices now that AZConfig is gone.
    factory = make_env_factory(
        SimpleNamespace(scenario=scenario),
        ObsConfig().to_engine_json(),
        master_seed=0,
    )
    env = factory(0)
    try:
        assert env._max_rounds == 3
        assert env._fix_dice == [2, 2, 2, 2, 0, 0, 0, 0]
        # obs_mask propagation is observable through the env's mask slot
        # arrays — non-empty when a mask is configured.
        assert env._mask_slots_per_perspective is not None
    finally:
        env.close()
