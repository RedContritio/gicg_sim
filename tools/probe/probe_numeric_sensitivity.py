"""Hook channel 响应度诊断: 量化 agent 对 hook token 扰动的敏感程度.

用法:
    .venv/bin/python -m tools.probe_numeric_sensitivity <ckpt_path> [--config c1_random|c1]

产出:
  - 针对 N 个随机 active hook 的 LitNumber / type 扰动,测每次扰动的 value 变化和 policy top1 变动
  - 针对多个不同游戏阶段(early/mid)的 obs 做重复测试
  - 对照: dyn counter_values 扰动(应有正常响应,确认 forward pipeline OK)
  - 汇总: "hook 敏感度" vs "counter 敏感度" 比值 — 可直接当判据

判读:
  - hook_response_ratio > 0.3  → hook channel 显著参与决策 (修复/训练生效) ✓
  - hook_response_ratio < 0.01 → hook channel 死 (C1v4/F 水平)
  - 0.01 ≤ ratio ≤ 0.3        → 有响应但弱,D1 可能不够,评估 D2

"响应度"定义: 对一批扰动(N=20-50 个随机 token),取 |Δvalue| 的 mean 和
policy top1 变动率 (变了/未变),两个维度。

Core perturbation / measurement primitives live in
``tools.probe_numeric_sensitivity_core`` — this file owns only the
CLI orchestration and verdict printing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from gicg_env import GicgEnv
from tools.probe.probe_numeric_sensitivity_core import (
    CONFIG_BUILDERS,
    aggregate,
    build_obs,
    load_cfg,
    measure_counter_response,
    measure_response,
    parse_hook_data,
    sample_perturbations,
)
from training.paradigms.az.network import Agent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('ckpt', type=str)
    ap.add_argument('--config', type=str, default='c1_random', choices=list(CONFIG_BUILDERS.keys()))
    ap.add_argument('--n-samples', type=int, default=30, help='perturbations per hook mode per obs')
    ap.add_argument(
        '--obs-steps',
        type=int,
        nargs='+',
        default=[2, 8, 14],
        help='game-depth of obs snapshots to test',
    )
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    ckpt = Path(args.ckpt)
    print(f'Loading: {ckpt}')
    cfg = load_cfg(args.config)
    agent = Agent(cfg.agent)
    agent.load(str(ckpt))

    # Build obs snapshots across multiple game stages.
    snapshots = []
    for step in args.obs_steps:
        env = GicgEnv(
            team_0=cfg.scenario.team_0,
            team_1=cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=args.seed,
            data_dir='data',
        )
        o = build_obs(env, step, args.seed)
        env.close()
        if o is None:
            print(f'  [skip step={step}] env terminated early')
            continue
        snapshots.append((step, o))
        print(f'  loaded obs step={step}: n_legal={len(o[2])}')

    if not snapshots:
        print('ERROR: no usable obs snapshots')
        return 1

    # Aggregate stats across all snapshots.
    rng = np.random.default_rng(args.seed)
    agg = {'lit_number': [], 'type_swap': [], 'counter': []}

    for step, (static, dyn, refs, payments) in snapshots:
        hook_data = parse_hook_data(static, cfg)
        n_active = int((hook_data[:, :, 0].sum(axis=1) != 0).sum())
        print(f'\n--- obs at step={step} (n_active_hooks={n_active}, n_legal={len(refs)}) ---')

        # LitNumber perturbations
        perts = sample_perturbations(hook_data, cfg, args.n_samples, rng, 'lit_number')
        if perts:
            stats = measure_response(agent, static, dyn, refs, payments, perts)
            agg['lit_number'].append(stats)
            print(f'  [hook LitNumber]  {stats}')

        # Type-swap perturbations
        perts = sample_perturbations(hook_data, cfg, args.n_samples, rng, 'type_swap')
        if perts:
            stats = measure_response(agent, static, dyn, refs, payments, perts)
            agg['type_swap'].append(stats)
            print(f'  [hook type-swap]  {stats}')

        # Counter baseline
        stats = measure_counter_response(
            agent,
            static,
            dyn,
            refs,
            payments,
            n_trials=args.n_samples,
            seed=args.seed + step,
        )
        agg['counter'].append(stats)
        print(f'  [counter_values]  {stats}')

    # Aggregate across snapshots
    lit = aggregate(agg['lit_number'])
    typ = aggregate(agg['type_swap'])
    cnt = aggregate(agg['counter'])

    print('\n' + '=' * 60)
    print('SUMMARY (aggregated across all obs)')
    print('=' * 60)
    if lit:
        print(f'hook LitNumber: {lit}')
    if typ:
        print(f'hook type-swap: {typ}')
    if cnt:
        print(f'counter_values: {cnt}  (baseline — pipeline sanity)')

    if lit and cnt:
        ratio_v = lit.value_abs_delta_mean / (cnt.value_abs_delta_mean + 1e-9)
        ratio_t = lit.top1_change_rate / (cnt.top1_change_rate + 1e-9)
        print('\nHook vs Counter response ratio:')
        print(f'  value_delta: {ratio_v:.3f}')
        print(f'  top1_change: {ratio_t:.3f}')
        print('\nVERDICT:')
        if ratio_v < 0.01 and ratio_t < 0.01:
            print('  ✗ HOOK CHANNEL DEAD (< 1% of counter response)')
            print('    → Expected for F-era ckpt (hook_encoder weights ≈ 0)')
        elif ratio_v > 0.3 or ratio_t > 0.3:
            print('  ✓ HOOK CHANNEL ACTIVE (> 30% of counter response)')
            print('    → hook_encoder participating in decisions')
        else:
            print('  ~ HOOK CHANNEL WEAK (1-30% of counter response)')
            print('    → Responds to hooks but weakly; consider D2 upgrade')

    return 0


if __name__ == '__main__':
    sys.exit(main())
