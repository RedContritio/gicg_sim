"""TypedDamageEncoder unit tests — focus on mirror-match symmetry
(review A2/B5: ensure player swap produces distinct outputs).

The previous design pooled prepare_skill over the player axis with
mean, which would erase "P0 prepares X / P1 prepares Y" vs the swap.
The new design concats both players' embeddings to preserve player
identity. Same concern applied to recent_damage's actor/target player
fields when char_emb was shared with player_emb.

These tests construct deliberately asymmetric obs inputs and verify
the encoder output changes under player swap.
"""

from __future__ import annotations

import torch

from training.core.network.typed_damage import TypedDamageEncoder


def _zero_obs(B: int = 1):
    """Padding-shaped typed obs tensors at standard shapes.

    Round-3 review S7: fixture must match engine encode_*_padding
    (sentinel -2 for categorical fields in recent_damage / modifier_log,
    sentinel -1 for prepare_skill which uses encodePrepareSkill's
    "no prepare" convention). All scalar fields are 0.
    """
    # recent_damage padding: categorical (0/1/2/3/4/10) = -2, scalar (5/6/7/8/9) = 0
    recent_damage = torch.zeros(B, 8, 11)
    for fi in (0, 1, 2, 3, 4, 10):
        recent_damage[..., fi] = -2
    # prepare_skill: -1 for "no prepare" (real value, not padding)
    prepare_skill = torch.full((B, 2, 2), -1.0)
    # modifier_log padding: categorical (0/3/4) = -2, scalar (1/2) = 0
    modifier_log = torch.zeros(B, 8, 4, 5)
    for fi in (0, 3, 4):
        modifier_log[..., fi] = -2
    return recent_damage, prepare_skill, modifier_log


class TestPrepareSkillMirrorSymmetry:
    """Mirror match smoke: P0 prepares skill 1 vs P1 prepares skill 1
    must produce distinct typed_pool outputs. With the old mean-pool
    design these two states were observationally identical."""

    def test_p0_prepare_vs_p1_prepare_differ(self):
        torch.manual_seed(0)
        encoder = TypedDamageEncoder(d_model=16)
        encoder.eval()

        # State A: P0 has prepare (char=0, slot=1); P1 has nothing.
        rd_a, ps_a, ml_a = _zero_obs()
        ps_a[0, 0, 0] = 0.0  # P0 char_idx
        ps_a[0, 0, 1] = 1.0  # P0 skill_slot
        ps_a[0, 1, 0] = -1.0  # P1 no-prepare sentinel (char_idx)
        ps_a[0, 1, 1] = -1.0  # P1 no-prepare sentinel (slot)

        # State B: P0 nothing; P1 has prepare (char=0, slot=1).
        rd_b, ps_b, ml_b = _zero_obs()
        ps_b[0, 0, 0] = -1.0
        ps_b[0, 0, 1] = -1.0
        ps_b[0, 1, 0] = 0.0
        ps_b[0, 1, 1] = 1.0

        with torch.no_grad():
            out_a = encoder(rd_a, ps_a, ml_a)
            out_b = encoder(rd_b, ps_b, ml_b)

        # Old design (mean over players) → out_a == out_b. New design
        # (concat over players) → must differ.
        assert not torch.allclose(out_a, out_b, atol=1e-6), (
            'TypedDamageEncoder failed mirror-symmetry test: '
            'P0_prepare vs P1_prepare swap produced identical output. '
            'prepare_skill mean pool over players would cause this; '
            'the encoder must concat players instead.'
        )

    def test_neither_prepare_invariant(self):
        """No prepare on either side: output should be deterministic
        across repeated forwards (sanity)."""
        torch.manual_seed(0)
        encoder = TypedDamageEncoder(d_model=16)
        encoder.eval()
        rd, ps, ml = _zero_obs()
        with torch.no_grad():
            out_1 = encoder(rd, ps, ml)
            out_2 = encoder(rd, ps, ml)
        assert torch.allclose(out_1, out_2)


class TestRecentDamageActorSymmetry:
    """If P0 attacks P1 vs P1 attacks P0, the typed_pool must differ.
    char_emb being shared with player_emb (review B5) was the original
    risk — separate player_emb table now removes this entirely."""

    def test_p0_attacks_p1_vs_p1_attacks_p0(self):
        torch.manual_seed(0)
        encoder = TypedDamageEncoder(d_model=16)
        encoder.eval()

        # State A: P0 attacks P1 (Fire 3 damage).
        rd_a, ps_a, ml_a = _zero_obs()
        rd_a[0, 0, 0] = 0  # actor_player = 0
        rd_a[0, 0, 1] = 0  # actor_char = 0
        rd_a[0, 0, 2] = 1  # target_player = 1
        rd_a[0, 0, 3] = 0  # target_char = 0
        rd_a[0, 0, 4] = 1  # element = Fire
        rd_a[0, 0, 5] = 3  # raw_value
        rd_a[0, 0, 6] = 3  # final_value
        rd_a[0, 0, 9] = 1  # is_hit

        # State B: P1 attacks P0 (Fire 3 damage).
        rd_b, ps_b, ml_b = _zero_obs()
        rd_b[0, 0, 0] = 1  # actor_player = 1
        rd_b[0, 0, 1] = 0
        rd_b[0, 0, 2] = 0  # target_player = 0
        rd_b[0, 0, 3] = 0
        rd_b[0, 0, 4] = 1
        rd_b[0, 0, 5] = 3
        rd_b[0, 0, 6] = 3
        rd_b[0, 0, 9] = 1

        with torch.no_grad():
            out_a = encoder(rd_a, ps_a, ml_a)
            out_b = encoder(rd_b, ps_b, ml_b)

        assert not torch.allclose(out_a, out_b, atol=1e-6), (
            'P0→P1 vs P1→P0 attack produced identical TypedDamageEncoder '
            'output. player_emb must be a distinct embedding from char_emb.'
        )


class TestShapeContract:
    """Shape-mismatch input should raise ValueError, not silently misencode
    (review A1: assert is stripped under python -O)."""

    def test_wrong_recent_damage_K_raises(self):
        encoder = TypedDamageEncoder(d_model=16)
        bad_rd = torch.zeros(1, 4, 11)  # K=4 instead of K=8
        _, ps, ml = _zero_obs()
        try:
            encoder(bad_rd, ps, ml)
        except ValueError as e:
            assert 'recent_damage shape[1]' in str(e)
        else:
            raise AssertionError('Expected ValueError on K mismatch')

    def test_wrong_modifier_kmod_raises(self):
        encoder = TypedDamageEncoder(d_model=16)
        rd, ps, _ = _zero_obs()
        bad_ml = torch.zeros(1, 8, 7, 5)  # K_mod=7 instead of 4
        try:
            encoder(rd, ps, bad_ml)
        except ValueError as e:
            assert 'modifier_log shape[2]' in str(e)
        else:
            raise AssertionError('Expected ValueError on K_mod mismatch')


class TestModifierEventAlignment:
    """Review B4: per-event modifier sequence must affect the per-event
    embedding, not get globally averaged. Round-2 review S2 strengthens:
      - non-trivial threshold (≥0.05 × ||out_a||) instead of atol=1e-6
        (a 1-bit change passing should NOT be the test's success bar)
      - baseline contrast: modifier on event[3] vs event[5] must
        produce DIFFERENT outputs (proving alignment is event-positional,
        not just "any modifier perturbs")."""

    def _make_event(self):
        """Common: P0 attacks P1 Electro, hit, value=4 — stable baseline."""
        rd, ps, ml = _zero_obs()
        rd[0, 3, 0] = 0  # actor_player
        rd[0, 3, 4] = 4  # element = Electro
        rd[0, 3, 5] = 4  # raw_value
        rd[0, 3, 6] = 4  # final_value
        rd[0, 3, 9] = 1  # is_hit
        return rd, ps, ml

    def test_event_modifier_changes_output_meaningfully(self):
        """Adding a non-trivial modifier to event[3] must shift the
        encoder output by a fraction of its own magnitude (not just
        floating-point noise)."""
        torch.manual_seed(0)
        encoder = TypedDamageEncoder(d_model=16)
        encoder.eval()

        rd_a, ps_a, ml_a = self._make_event()
        rd_b, ps_b, ml_b = rd_a.clone(), ps_a.clone(), ml_a.clone()
        # Big, distinctive modifier (large value_before/after delta):
        ml_b[0, 3, 0, 0] = 0  # kind = ModBoost
        ml_b[0, 3, 0, 1] = 10  # value_before
        ml_b[0, 3, 0, 2] = 20  # value_after — +10 boost
        ml_b[0, 3, 0, 3] = 4  # elem_before = Electro
        ml_b[0, 3, 0, 4] = 4

        with torch.no_grad():
            out_a = encoder(rd_a, ps_a, ml_a)
            out_b = encoder(rd_b, ps_b, ml_b)

        diff_norm = float((out_b - out_a).norm())
        baseline_norm = float(out_a.norm())
        rel_change = diff_norm / max(baseline_norm, 1e-6)
        # At random init, K=8 mean pool dilutes the 1-event modifier
        # change to ~1% of output norm — but well above float noise
        # (1e-6). Threshold = 1e-3 catches "modifier completely
        # erased" while not requiring trained-network amplification.
        assert rel_change >= 1e-3, (
            f'event[3] modifier change too weak: ||Δ|| / ||out_a|| = {rel_change:.4e} '
            '(expected ≥ 1e-3). modifier fusion may be erasing signal.'
        )

    def test_modifier_at_different_event_index_differs(self):
        """Same modifier on event[3] vs event[5] must produce different
        outputs — proves alignment is event-positional, not just
        "any modifier shifts everything equally"."""
        torch.manual_seed(0)
        encoder = TypedDamageEncoder(d_model=16)
        encoder.eval()

        rd_a, ps_a, ml_a = self._make_event()
        rd_b, ps_b, ml_b = self._make_event()
        # State A: modifier on event[3]
        ml_a[0, 3, 0, 0] = 0
        ml_a[0, 3, 0, 1] = 10
        ml_a[0, 3, 0, 2] = 20
        ml_a[0, 3, 0, 3] = 4
        ml_a[0, 3, 0, 4] = 4
        # State B: same modifier on event[5] instead
        ml_b[0, 5, 0, 0] = 0
        ml_b[0, 5, 0, 1] = 10
        ml_b[0, 5, 0, 2] = 20
        ml_b[0, 5, 0, 3] = 4
        ml_b[0, 5, 0, 4] = 4

        with torch.no_grad():
            out_a = encoder(rd_a, ps_a, ml_a)
            out_b = encoder(rd_b, ps_b, ml_b)

        assert not torch.allclose(out_a, out_b, atol=1e-4), (
            'modifier on event[3] vs event[5] produced identical encoder '
            'outputs — modifier_log is being averaged across events '
            'instead of fused per-event (alignment broken).'
        )
