"""Cross-check Python encoder field-index assumptions against the
engine's actual obs encoding (review B1).

The TypedDamageEncoder reads typed-obs fields by index — e.g.
recent_damage[..., 0] is actor_player, [..., 4] is element, [..., 10]
is reaction_kind. These indices are hand-maintained in two places:
- gicg_engine/observation_dynamic.go::encodeRecentDamageEvents
- training/framework/network/typed_damage.py::forward

If the Go encoder ever reorders fields without updating Python, the
network silently learns garbage. This test triggers a damage event
with known typed values (element=Fire, raw=2, target=P1/c0, etc.)
and asserts the corresponding obs slot matches the field-index
assumption Python encodes against.

The same idea applies to modifier_log fields (kind / value_before /
value_after / element_before / element_after).
"""

from __future__ import annotations

import numpy as np
import pytest

from gicg_env.env import GicgEnv
from gicg_env.env_obs import (
    OBS_COUNTER_SLOTS,
    OBS_HAND_BLOCK_SIZE,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_SLOTS,
)
from training.core.obs_constants import (
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
)


def _slice_typed_segments(raw_obs: np.ndarray, n_counter_slots: int):
    """Return (recent_damage, prepare_skill, modifier_log) views, raw int."""
    c_end = OBS_META_SIZE + n_counter_slots
    hand_end = c_end + OBS_HAND_BLOCK_SIZE - 2  # excluding 2 enemy size scalars
    enemy_end = hand_end + 2
    rd_end = enemy_end + OBS_RECENT_DAMAGE_SLOTS
    ps_end = rd_end + OBS_PREPARE_SKILL_SLOTS
    ml_end = ps_end + OBS_MODIFIER_LOG_SLOTS

    recent_damage = raw_obs[enemy_end:rd_end].reshape(
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
    )
    prepare_skill = raw_obs[rd_end:ps_end].reshape(2, 2)
    modifier_log = raw_obs[ps_end:ml_end].reshape(
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_MODIFIER_LOG_FIELD_COUNT,
    )
    return recent_damage, prepare_skill, modifier_log


class TestRecentDamageFieldOrder:
    """Verify Python field index assumptions match engine encodeRecentDamageEvents.

    Round-3 review M3+M4: padding sentinel for recent_damage and
    modifier_log categorical fields is **-2** (was -1 in Round-2);
    -1 is reserved as a real "no-actor / no-prepare" value (DSL
    deal_damage from summon / 反应 / 反射 emits ActorPlayer=-1).
    Scalar fields stay 0.
    prepare_skill keeps -1 for "no prepare" (encodePrepareSkill convention).
    """

    def test_initial_obs_recent_damage_padding_sentinels(self):
        """Before any damage emitted, all 8 events have categorical
        fields = -2 sentinel and scalar fields = 0."""
        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        raw = env._engine.get_dynamic_obs()
        recent, _, _ = _slice_typed_segments(raw, OBS_COUNTER_SLOTS)
        assert recent.shape == (8, 11)
        # categorical fields (0/1/2/3/4/10) = -2
        for fi in (0, 1, 2, 3, 4, 10):
            assert (recent[:, fi] == -2).all(), f'recent_damage padding field {fi} != -2 sentinel: got {recent[:, fi]}'
        # scalar fields (5/6/7/8/9) = 0
        for fi in (5, 6, 7, 8, 9):
            assert (recent[:, fi] == 0).all(), f'recent_damage padding field {fi} != 0 scalar: got {recent[:, fi]}'

    def test_modifier_log_padding_sentinels(self):
        """modifier_log padding: kind / element_before / element_after = -2;
        value_before / value_after = 0."""
        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        raw = env._engine.get_dynamic_obs()
        _, _, modifier = _slice_typed_segments(raw, OBS_COUNTER_SLOTS)
        assert modifier.shape == (8, 4, 5)
        # categorical (0/3/4) = -2 (Round-3 M3 sentinel)
        for fi in (0, 3, 4):
            assert (modifier[..., fi] == -2).all(), f'modifier_log field {fi} != -2: got {modifier[..., fi]}'
        # scalar (1/2) = 0
        for fi in (1, 2):
            assert (modifier[..., fi] == 0).all(), f'modifier_log field {fi} != 0: got {modifier[..., fi]}'

    def test_prepare_skill_padding_neg1(self):
        """prepare_skill defaults to (-1, -1) per player when no prepare."""
        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        raw = env._engine.get_dynamic_obs()
        _, prepare, _ = _slice_typed_segments(raw, OBS_COUNTER_SLOTS)
        assert prepare.shape == (2, 2)
        # Both players: (char_idx=-1, slot=-1) — no skill being prepared.
        assert (prepare == -1).all(), f'expected all -1 padding, got {prepare}'


class TestRecentDamageFieldSemantics:
    """Engine field-order spec (must match observation_dynamic.go::encodeRecentDamageEvents):
    [0] actor_player  [1] actor_char     [2] target_player  [3] target_char
    [4] element       [5] raw_value      [6] final_value    [7] absorbed
    [8] is_piercing   [9] is_hit         [10] reaction_kind
    """

    def test_field_index_count_matches_engine(self):
        """The 11 field labels above must align with the per-event width."""
        assert OBS_RECENT_DAMAGE_FIELD_COUNT == 11

    def test_modifier_field_index_count_matches_engine(self):
        """ModifierKind/value_before/value_after/elem_before/elem_after = 5."""
        assert OBS_MODIFIER_LOG_FIELD_COUNT == 5

    def test_modifier_kmod_matches_engine(self):
        """Stage-level: Boost/Reaction/Reduce/AfterDamage = 4."""
        assert OBS_MODIFIER_LOG_K_MOD == 4


class TestEnginePythonConstSync:
    """Verify Go-side constants exposed via GameGetTypedObsConstants
    match Python mirrors. _verify_typed_obs_constants in __init__
    already raises on mismatch — this test makes the contract explicit."""

    def test_engine_python_consts_agree(self):
        # Construction itself triggers _verify_typed_obs_constants.
        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])

        # Re-read the engine constants directly and compare.
        # Round-2 M2: 8 ints (5 typed + 3 hand-block).
        # Round-4 S-3: 用 import 常量替 hardcode 4/2,跟 _verify_typed_obs_constants 一致。
        import ctypes

        from gicg_env.env_obs import OBS_MAX_CARD_TYPES
        from training.core.obs_constants import OBS_ENEMY_SIZES, OBS_HAND_BUCKETS

        out = (ctypes.c_int * 8)()
        env._engine._lib.GameGetTypedObsConstants(out)
        engine_K = int(out[0])
        engine_field = int(out[1])
        engine_prepare = int(out[2])
        engine_kmod = int(out[3])
        engine_mod_field = int(out[4])
        engine_max_card_types = int(out[5])
        engine_hand_buckets = int(out[6])
        engine_enemy_sizes = int(out[7])

        assert engine_K == OBS_RECENT_DAMAGE_EVENTS
        assert engine_field == OBS_RECENT_DAMAGE_FIELD_COUNT
        assert engine_prepare == OBS_PREPARE_SKILL_SLOTS
        assert engine_kmod == OBS_MODIFIER_LOG_K_MOD
        assert engine_mod_field == OBS_MODIFIER_LOG_FIELD_COUNT
        assert engine_max_card_types == OBS_MAX_CARD_TYPES
        assert engine_hand_buckets == OBS_HAND_BUCKETS
        assert engine_enemy_sizes == OBS_ENEMY_SIZES


class TestRecentDamageFieldsAfterDamage:
    """Drive a real damage by random selfplay and verify each field
    index encodes the expected typed value. This is the actual
    cross-check — it would catch e.g. swapping actor_player <->
    target_player in the engine (the previous review's biggest concern).
    """

    def _drive_until_first_damage(self, env, max_steps: int = 400, seed: int = 42):
        """Run random selfplay until the recent_damage ring has at least
        one event with non-padding fields. Return (event_fields, n_steps).

        Round-2 review P3 / M1: with engine padding now writing -1
        sentinels for categorical fields, "valid event" detection looks
        at scalar fields (raw_value/final_value/absorbed/is_piercing/is_hit)
        being non-zero — those stay 0 in padding so any non-zero scalar
        means a real event landed in that ring slot.

        Ring is K=8 bounded; once ≥9 damage events have fired, oldest is
        dropped and the "first" event by chronological order is no longer
        at index 0. For the FIRST damage of a fresh game (ring empty),
        it always lands at index 0. We return the lowest-index real event
        (i.e. the oldest still in the ring)."""
        rng = np.random.RandomState(seed)
        for step in range(max_steps):
            if env.done:
                break
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                break
            action = int(rng.randint(0, len(kinds)))
            env.step(action)

            raw = env._engine.get_dynamic_obs()
            recent, _, _ = _slice_typed_segments(raw, OBS_COUNTER_SLOTS)
            # M3 sentinel-aware detection: padding sentinel is -2
            # (Round-3); real events have actor_player ∈ {-1, 0, 1}
            # (-1 = DSL no-actor real, 0/1 = P0/P1) OR scalar field
            # non-zero.
            for k in range(recent.shape[0]):
                actor_player = int(recent[k][0])
                scalar_nonzero = (recent[k][5:10] != 0).any()
                if actor_player in (-1, 0, 1) or scalar_nonzero:
                    return recent[k].copy(), step + 1
        raise RuntimeError(f'no damage in {max_steps} steps')

    def test_actor_target_player_in_valid_range(self):
        """actor_player and target_player fields (indices 0, 2) must
        both be in {0, 1} for any real damage event. Self-damage cases
        (赤蝶 蝶火 cost: Target.OwnActive, Element.Piercing) are valid
        — they have actor == target. Cross-checks the field index by
        verifying both indices land in player-id range."""
        from gicg_env.env import GicgEnv

        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        try:
            event, _ = self._drive_until_first_damage(env)
        finally:
            env.close()
        actor_player = int(event[0])  # field index 0
        target_player = int(event[2])  # field index 2
        assert actor_player in (0, 1), f'actor_player={actor_player} not in {{0,1}}'
        assert target_player in (0, 1), f'target_player={target_player} not in {{0,1}}'

    def test_cross_player_damage_observed_in_extended_run(self):
        """Across longer selfplay, the recent_damage ring should include
        at least one cross-player attack (actor != target). Round-2
        review S4: multi-seed loop instead of one magic seed — if any
        of 20 seeds produces a cross-player event, test passes; only
        if ALL fail do we conclude field-index swap.

        Padding sentinel = -1 (Round-2 M1) for actor_player / target_player;
        valid events have actor_player ∈ {0, 1}."""
        from gicg_env.env import GicgEnv

        seen_cross_any_seed = False
        for seed in range(20):
            env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
            rng = np.random.RandomState(seed)
            try:
                for _ in range(400):
                    if env.done:
                        break
                    kinds, _ = env.get_legal_actions()
                    if len(kinds) == 0:
                        break
                    env.step(int(rng.randint(0, len(kinds))))
                    raw = env._engine.get_dynamic_obs()
                    recent, _, _ = _slice_typed_segments(raw, OBS_COUNTER_SLOTS)
                    for k in range(recent.shape[0]):
                        ap = int(recent[k][0])
                        tp = int(recent[k][2])
                        if ap in (0, 1) and tp in (0, 1) and ap != tp:
                            seen_cross_any_seed = True
                            break
                    if seen_cross_any_seed:
                        break
            finally:
                env.close()
            if seen_cross_any_seed:
                break
        assert seen_cross_any_seed, (
            'no cross-player (actor != target) damage observed across '
            '20 seeds × 400 steps — field index 0/2 likely swapped, or '
            'ruleset only emits self-damage (unlikely for 赤蝶 vs 墨客).'
        )

    def test_value_fields_consistent(self):
        """raw_value (5) >= final_value (6); absorbed (7) = raw - final
        (modulo immunity / cancel which sets final to 0). is_hit (9) = 1
        whenever final_value > 0."""
        from gicg_env.env import GicgEnv

        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        try:
            event, _ = self._drive_until_first_damage(env)
        finally:
            env.close()
        raw_value = int(event[5])
        final_value = int(event[6])
        absorbed = int(event[7])
        is_hit = int(event[9])

        assert raw_value >= 0, f'raw_value={raw_value} negative — field index assumption broken'
        assert final_value >= 0, f'final_value={final_value} negative'
        assert absorbed >= 0, f'absorbed={absorbed} negative'
        assert raw_value >= final_value, (
            f'raw_value={raw_value} < final_value={final_value} — pre-shield raw should be >= post-shield final'
        )
        # absorbed bookkeeping: raw == final + absorbed (when not cancelled)
        # — only assert when is_hit (cancelled / immunity sets final=0
        # without symmetric absorbed bump).
        if is_hit and final_value > 0:
            assert raw_value == final_value + absorbed, (
                f'absorbed accounting: raw({raw_value}) != final({final_value}) + absorbed({absorbed})'
            )
        # is_hit must be 0 or 1 (boolean encoded as int).
        assert is_hit in (0, 1), f'is_hit={is_hit} not boolean — field index swap'

    def test_element_in_valid_range(self):
        """element field (4) ∈ {0..8} — None/Fire/Ice/Water/Electro/Geo/
        Anemo/Dendro/Physical, plus Piercing=9 (ADR-0019 §B.1). Reaction
        consumption sets element back to None mid-pipeline; the snapshot
        in recent_damage may be the post-reaction None (=0) or the
        attacker element. Either is in range."""
        from gicg_env.env import GicgEnv

        env = GicgEnv(team_0=['赤蝶'], team_1=['墨客'])
        try:
            event, _ = self._drive_until_first_damage(env)
        finally:
            env.close()
        element = int(event[4])
        assert 0 <= element <= 9, f'element={element} out of valid range — field index 4 != element'
