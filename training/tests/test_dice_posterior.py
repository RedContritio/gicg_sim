"""D3: Bayesian dice posterior property tests."""

from __future__ import annotations

import random

import numpy as np
import pytest

from training.paradigms.az.determinize import sample_opponent_dice

N_COLORS = 8


def _draw_many(n_samples, total, **kwargs):
    """Draw n_samples times, return per-color aggregate."""
    rng = random.Random(42)
    totals = np.zeros(N_COLORS, dtype=np.int64)
    for _ in range(n_samples):
        s = sample_opponent_dice(rng, total, **kwargs)
        totals += s
    return totals


def test_uniform_prior_when_no_evidence_is_balanced():
    """paid_counts=None, tuned_out_counts=None → α=(1,...,1) Dirichlet-
    Multinomial. Expected per-color marginal = total_dice / 8 (均衡),
    但 Dirichlet 采样每次都给不同 p,合成方差比纯 uniform 多 ~1.2x。
    不能用 chi²-vs-uniform 阈值(那是 multinomial 分布才成立)。
    改成:验证所有 color 的 aggregate 在期望 ±15% 以内。"""
    N = 10000
    total = 10
    totals = _draw_many(N, total=total)
    expected_per_color = N * total / N_COLORS  # = 12500
    # Dirichlet(1,...,1) → E[p] 均衡,长期 aggregate 应接近 expected
    max_dev = float(np.max(np.abs(totals - expected_per_color)) / expected_per_color)
    assert max_dev < 0.15, (
        f'max color deviation from balanced = {max_dev:.3f} > 15% — '
        f'suspects a non-uniform bug. Totals: {totals.tolist()}'
    )


def test_sum_equals_total():
    """Every single sample must sum to total_count exactly."""
    rng = random.Random(0)
    for _ in range(100):
        s = sample_opponent_dice(rng, total_count=10)
        assert int(s.sum()) == 10


def test_all_nonnegative():
    """Multinomial always non-negative; sanity check."""
    rng = random.Random(0)
    for _ in range(100):
        s = sample_opponent_dice(rng, total_count=8)
        assert np.all(s >= 0)


def test_zero_total_returns_zeros():
    """total_count=0 → all-zero array (no dice to sample)."""
    rng = random.Random(0)
    s = sample_opponent_dice(rng, total_count=0, paid_counts=[3, 0, 0, 0, 0, 0, 0, 0])
    assert np.array_equal(s, np.zeros(N_COLORS, dtype=np.int32))


def test_paid_evidence_skews_posterior_toward_paid_colors():
    """paid=[5,5,0,...,0] → posterior favors colors 0+1 (they had lots
    historically → current remaining share skews that way too).
    α=(6,6,1,1,1,1,1,1) → E[p_0+p_1]=12/18=2/3; expected ratio
    (paid colors) : (other) ≈ 2:1."""
    paid = [5, 5, 0, 0, 0, 0, 0, 0]
    totals = _draw_many(5000, total=10, paid_counts=paid)
    paid_sum = int(totals[0] + totals[1])
    other_sum = int(totals[2:].sum())
    ratio = paid_sum / max(other_sum, 1)
    assert 1.7 < ratio < 2.3, f'paid=[5,5,...] ratio paid-colors:other = {ratio:.3f}, expected ≈ 2.0'


def test_tuned_out_evidence_has_same_semantic_as_paid():
    """tuned_out_counts enters α with same weight as paid_counts —
    same evidence type, same posterior effect. Swapping the two or
    summing into one should yield statistically equivalent results."""
    rng1 = random.Random(99)
    totals_paid = np.zeros(N_COLORS, dtype=np.int64)
    for _ in range(5000):
        s = sample_opponent_dice(
            rng1,
            total_count=10,
            paid_counts=[3, 2, 0, 0, 0, 0, 0, 0],
            tuned_out_counts=None,
        )
        totals_paid += s

    rng2 = random.Random(99)
    totals_mixed = np.zeros(N_COLORS, dtype=np.int64)
    for _ in range(5000):
        s = sample_opponent_dice(
            rng2,
            total_count=10,
            paid_counts=[2, 1, 0, 0, 0, 0, 0, 0],
            tuned_out_counts=[1, 1, 0, 0, 0, 0, 0, 0],
        )
        totals_mixed += s

    # The two setups have the same α (1+3+0 vs 1+2+1 = 4; 1+2+0 vs 1+1+1 = 3)
    # → sampling distribution should be equivalent; compare per-color totals.
    diff = np.abs(totals_paid - totals_mixed).astype(float)
    # Chi² style: diff magnitude should be small vs expected count
    max_diff_frac = diff.max() / max(totals_paid.mean(), 1)
    assert max_diff_frac < 0.10, (
        f'splitting paid→tuned_out should not change distribution (max diff fraction {max_diff_frac:.3f})'
    )


def test_invalid_paid_counts_length_raises():
    rng = random.Random(0)
    with pytest.raises(ValueError, match='paid_counts length'):
        sample_opponent_dice(rng, 10, paid_counts=[1, 2, 3])  # length 3 ≠ 8


def test_invalid_tuned_out_length_raises():
    rng = random.Random(0)
    with pytest.raises(ValueError, match='tuned_out_counts length'):
        sample_opponent_dice(rng, 10, tuned_out_counts=[1, 2])
