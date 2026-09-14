"""Determinize 采样分布诊断(Step 2)。

运行 N=10000 次 sample_hidden_state,验证:
  (a) 7 条硬不变量 I1-I7 全部通过(若任一失败 → 实现 bug)
  (b) D1 设计缺陷的实际影响(pool 构造用 p0 hand + filler 带来的多样性损失)
  (c) D2 设计缺陷的实际影响(dice uniform 先验偏差)

场景:异质 card_pool + 异质双方团队,放大 D1 的可见性。

Usage:
    .venv/bin/python -m tools.debug.diag_determinize
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from gicg_env import GicgEnv
from gicg_env.engine import preload_dsl
from training.paradigms.az.determinize import (
    SharedFixedPool,
    _build_public_observation,
    _subtract_public,
    sample_hidden_state,
    sample_opponent_dice,
)
from training.paradigms.az.pool_spec import resolve_pool_refs

N = 10_000


def _scenario():
    """异质场景:L1-L6 卡池全开,双方团队完全不重叠。这样对手真实 hand 的
    ref 分布和 p0 hand 差异最大,能放大 D1 的设计缺陷。

    team_0 = [赤蝶, 猫咪](剑 + 弓)
    team_1 = [刻师傅, 天星](geo + electro)
    card_pool = None(全池,~30 张)
    """

    class Scenario:
        team_0 = ['赤蝶', '猫咪']
        team_1 = ['刻师傅', '天星']
        card_pool = None
        data_dir = 'data'

    return Scenario()


def _new_env(scenario, seed):
    env = GicgEnv(
        scenario.team_0,
        scenario.team_1,
        card_pool=scenario.card_pool,
        seed=seed,
        data_dir=scenario.data_dir,
    )
    env.reset(seed=seed)
    # 走到 PhaseAction(跨过 SelectActive)
    while env._engine.phase == 1:
        env.step(0)
        if env.done:
            break
    return env


def _run_invariant_test(scenario, pool_refs):
    """对 N=10000 个 sample 逐个验证 I1-I7。聚合 violation 数量."""
    print(f'\n=== invariant test (N={N}) ===')

    env = _new_env(scenario, seed=42)
    viewing_player = 0
    opponent = 1
    pub = _build_public_observation(env, viewing_player)
    opp_dice_total = env._engine.dice_total(opponent)
    pool_spec = SharedFixedPool(pool_refs)

    remaining = _subtract_public(pool_refs, pub.opponent_discard)
    remaining_mset = Counter(remaining)

    violations = {k: 0 for k in ('I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7')}
    uniques = set()

    rng = random.Random(0)
    for i in range(N):
        rng_i = random.Random(i * 7919)
        hidden = sample_hidden_state(
            env,
            viewing_player,
            pool_spec,
            rng_i,
            opponent_dice_total=opp_dice_total,
        )

        # I1 hand size
        if len(hidden.opponent_hand) != pub.opponent_hand_size:
            violations['I1'] += 1
        # I2 deck size
        if len(hidden.opponent_deck) != pub.opponent_deck_count:
            violations['I2'] += 1
        # I3 all refs ∈ remaining
        for ref in list(hidden.opponent_hand) + list(hidden.opponent_deck):
            if ref not in remaining_mset:
                violations['I3'] += 1
                break
        # I4 multiset 不超过 remaining
        sampled = Counter(list(hidden.opponent_hand) + list(hidden.opponent_deck))
        for ref, cnt in sampled.items():
            if cnt > remaining_mset.get(ref, 0):
                violations['I4'] += 1
                break
        # I5 dice sum
        if hidden.opponent_dice_colors is not None:
            if int(hidden.opponent_dice_colors.sum()) != opp_dice_total:
                violations['I5'] += 1
            # I6 dice >= 0
            if np.any(hidden.opponent_dice_colors < 0):
                violations['I6'] += 1
        # I7 uniqueness — 用 hidden 结构的 tuple 哈希
        key = (tuple(hidden.opponent_hand), tuple(hidden.opponent_deck))
        uniques.add(key)

    # I7: 不同 seed 应该产出不同 hidden。但在小 pool(low distinct refs)下
    # 采样空间本身小,collision 率期望较高。这里用宽阈值(>50%),真正的
    # I7 违反是 "< 5% unique"(采样器退化到单一结果)。
    i7_pass = len(uniques) > N * 0.5 if N > 100 else True
    print(f'  unique samples: {len(uniques)}/{N} (pool 小时 collision 正常;I7 阈值 >{N // 2} 判 pass)')
    print(f'  I7_pass={i7_pass}')
    for k, v in violations.items():
        status = '✓' if v == 0 else f'✗ ({v} violations)'
        print(f'  {k}: {status}')

    return all(v == 0 for v in violations.values()) and i7_pass


def _run_distribution_test(scenario, pool_refs):
    """统计对手 hand 里每个 ref 的命中频率,比对理论期望(均匀无放回从 remaining
    里抽 hand_size 张)。"""
    print(f'\n=== distribution test (N={N}) ===')

    env = _new_env(scenario, seed=42)
    viewing_player = 0
    opponent = 1
    pub = _build_public_observation(env, viewing_player)
    opp_dice_total = env._engine.dice_total(opponent)
    pool_spec = SharedFixedPool(pool_refs)

    remaining = _subtract_public(pool_refs, pub.opponent_discard)
    remaining_mset = Counter(remaining)
    total_remaining = sum(remaining_mset.values())
    hand_size = pub.opponent_hand_size
    deck_size = pub.opponent_deck_count

    print(f'  scenario: team_0={scenario.team_0} team_1={scenario.team_1}')
    print(f'  hand_size={hand_size} deck_size={deck_size}')
    print(f'  pool_refs len={len(pool_refs)} unique_types={len(set(pool_refs))}')
    print(f'  remaining (after discard subtract): len={total_remaining} unique={len(remaining_mset)}')
    print(f'  pool ref multiset (top 5 by count):')
    for ref, cnt in Counter(pool_refs).most_common(5):
        print(f'    ref={ref} count={cnt}')

    # 采样统计
    hand_ref_counts = Counter()
    for i in range(N):
        rng = random.Random(i * 7919 + 1)
        hidden = sample_hidden_state(
            env,
            viewing_player,
            pool_spec,
            rng,
            opponent_dice_total=opp_dice_total,
        )
        for r in hidden.opponent_hand:
            hand_ref_counts[r] += 1

    print(f'\n  sampled opponent hand: top 5 refs by frequency')
    for ref, cnt in hand_ref_counts.most_common(5):
        freq = cnt / (N * hand_size)
        expected = remaining_mset.get(ref, 0) / total_remaining if total_remaining > 0 else 0
        ratio = freq / expected if expected > 0 else float('inf')
        print(f'    ref={ref} observed_freq={freq:.4f} expected={expected:.4f} ratio={ratio:.2f}')

    # 关键统计:有多少比例的 hand ref 是 filler?
    filler_ref = pool_refs[0] if pool_refs else -1
    filler_count = hand_ref_counts.get(filler_ref, 0)
    filler_share = filler_count / (N * hand_size) if hand_size > 0 else 0
    theoretical_filler = remaining_mset.get(filler_ref, 0) / total_remaining if total_remaining > 0 else 0
    print(f'\n  filler analysis:')
    print(f'    filler_ref={filler_ref}')
    print(f'    sampled filler share in opponent hand: {filler_share:.4f}')
    print(f'    theoretical (if pool = remaining): {theoretical_filler:.4f}')
    print(f'    diff = {filler_share - theoretical_filler:+.4f}')


def _run_dice_test(total=10):
    """验证 dice 采样 Bayesian 行为:
    (a) 无支付观察 → 后验退化为 uniform(Dirichlet(1,1,..,1))
    (b) 有支付观察 → 后验压低已大量支付的 color 概率
    """
    print(f'\n=== dice distribution test (N={N}, total={total}) ===')

    # (a) uniform prior (no paid observations)
    rng = random.Random(0)
    color_totals = np.zeros(8, dtype=np.int64)
    for _ in range(N):
        sample = sample_opponent_dice(rng, total, paid_counts=None)
        color_totals += sample

    expected = N * total / 8
    chi2 = float(np.sum((color_totals - expected) ** 2 / expected))
    print(f'  [无支付观察] per-color totals (expected {expected:.0f}): {color_totals.tolist()}')
    print(f'  chi-square vs uniform: {chi2:.2f} (df=7, 95% threshold ≈ 14.07)')
    if chi2 > 14.07:
        print(f'  ⚠ 拒绝均匀假设 (chi2>14.07)')
    else:
        print(f'  ✓ 不拒绝均匀假设(Dirichlet 后验退化正确)')

    # (b) Bayesian posterior with heavy payments on colors 0,1 → those
    # colors should get MORE draws (more observed = α_i increased)
    #
    # Wait — if opponent paid lots of fire & ice, does posterior say
    # they have MORE or LESS of those left? Intuition: they PROBABLY
    # rolled a lot of fire & ice originally (else couldn't have paid so
    # many). So remaining per-color share is also skewed toward those.
    #
    # Dirichlet posterior: α = 1 + paid, so paid colors get HIGHER mean
    # proportion → more draws for remaining. This reflects "they had
    # a lot of those, still probably have more than other colors."
    paid = [5, 5, 0, 0, 0, 0, 0, 0]  # heavy fire + ice payment
    color_totals = np.zeros(8, dtype=np.int64)
    rng = random.Random(1)
    for _ in range(N):
        sample = sample_opponent_dice(rng, total, paid_counts=paid)
        color_totals += sample

    fire_ice = int(color_totals[0] + color_totals[1])
    other = int(color_totals[2:].sum())
    # α_0 = α_1 = 6; α_2..7 = 1. Expected fractions: 12/18 (fire+ice),
    # 6/18 (other 6 colors combined). 12:6 = 2:1.
    expected_ratio = 2.0
    actual_ratio = fire_ice / max(other, 1)
    print(f'  [paid=[5,5,0,0,0,0,0,0]] per-color totals: {color_totals.tolist()}')
    print(f'  fire+ice draws = {fire_ice}, other-6 draws = {other}')
    print(f'  ratio = {actual_ratio:.3f}  (expected {expected_ratio:.3f})')
    if abs(actual_ratio - expected_ratio) < 0.1:
        print(f'  ✓ Bayesian 后验形状符合预期(paid 越多,残余 share 越高)')
    else:
        print(f'  ⚠ 偏差 {abs(actual_ratio - expected_ratio):.3f}(可能是采样噪声或实现偏)')


def main() -> int:
    print('=== determinize 采样分布诊断 ===')
    print(f'N = {N}')
    preload_dsl('data')
    scenario = _scenario()
    print(
        f'scenario: team_0={scenario.team_0} team_1={scenario.team_1} '
        f'card_pool={"ALL" if scenario.card_pool is None else scenario.card_pool}'
    )

    # resolve_pool_refs 返回 {0: p0_deck, 1: p1_deck}。viewing_player=0,
    # 对手是 1,所以采样时 PerOpponentPool 会用 pool_by_player[1]。此诊断
    # 一律用 p1 的 deck 作为 pool_refs 基线(对手的真实池),和训练时一致。
    pool_by_player = resolve_pool_refs(scenario)
    for p in (0, 1):
        refs = pool_by_player[p]
        print(f'  pool[player={p}]: len={len(refs)} unique={len(set(refs))}')
    pool_refs = pool_by_player[1]  # opponent's deck as ground truth
    print(
        f'resolved pool_refs (opponent=1): len={len(pool_refs)} '
        f'unique_types={len(set(pool_refs))} filler_ref={pool_refs[0] if pool_refs else -1}'
    )

    ok = _run_invariant_test(scenario, pool_refs)
    _run_distribution_test(scenario, pool_refs)
    _run_dice_test()

    print('\n=== summary ===')
    if ok:
        print('✓ 所有硬不变量 I1-I7 通过 — 实现按 MVP 契约无 bug')
    else:
        print('✗ 有硬不变量违反 — 实现存在 bug,需修复')
    print('  分布测试:观察 filler ref 在对手 hand 中的实际占比 vs 理论占比,差距反映 D1 设计缺陷的实际影响量')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
