"""Paradigm-agnostic ckpt evaluator + replay dumper. Replaces
dmc_eval_ckpt.py + dmc_dump_replay.py.

Usage::

    # 多 ckpt 同 scenarios deterministic 对比(T-06 ckpts/ subdir layout)
    .venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_pilot.toml \\
        --ckpts artifacts/A/ckpts/latest.pt artifacts/B/ckpts/latest.pt \\
        --baselines random F1-D2 F1-D4 --n-scenarios 128 \\
        --output-dir /tmp/cmp/

    # 出 replay yaml(diff 两 ckpt 策略)
    .venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_pilot.toml \\
        --ckpts artifacts/A/ckpts/latest.pt artifacts/B/ckpts/latest.pt --baselines F1-D2 \\
        --record-replays --output-dir /tmp/cmp/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _ckpt_label(p: Path) -> str:
    """Extract human-readable run label from ckpt path.

    Post-T-06 layout: ckpts/ subdir 包所有 .pt,run_label = ckpt 的 grandparent::

        /x/y/202605151019_000069_dmc_stage3_pilot/ckpts/latest.pt
        →   202605151019_000069_dmc_stage3_pilot

    若 parent dir 名非 ``ckpts``(说明 caller 传 flat path 或非标准 layout),
    raise ValueError — clean-slate 不留 flat 兼容(spec 行 76-96 / 606-613)。
    """
    if p.parent.name != 'ckpts':
        raise ValueError(
            f'ckpt path must live under <run>/ckpts/ subdir (T-06 layout); got parent={p.parent.name!r} for {p}'
        )
    return p.parent.parent.name


def main():
    p = argparse.ArgumentParser()
    p.add_argument('config', type=str)
    p.add_argument('--paradigm', default='dmc')
    p.add_argument('--ckpts', nargs='+', required=True)
    p.add_argument('--baselines', nargs='+', required=True)
    p.add_argument('--n-scenarios', type=int, default=128)
    p.add_argument('--scenarios-seed', type=int, default=None)
    p.add_argument('--data-dir', type=str, default='data')
    p.add_argument('--output-dir', type=str, default=None)
    p.add_argument('--record-replays', action='store_true')
    p.add_argument(
        '--save-both-win',
        action='store_true',
        help='only record scenarios where ckpt wins both swap-sides vs baseline',
    )
    p.add_argument('--only-sid', type=int, default=-1)
    args = p.parse_args()

    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')

    from tools.eval._paradigm import resolve

    load_config = resolve(args.paradigm, 'load_config')
    build_agent = resolve(args.paradigm, 'build_agent')
    build_evaluator = resolve(args.paradigm, 'build_evaluator')

    cfg = load_config(args.config, data_dir=args.data_dir)
    cfg.eval.baselines = list(args.baselines)
    cfg.eval.n_scenarios = args.n_scenarios
    if args.scenarios_seed is not None:
        cfg.eval.scenarios_seed = args.scenarios_seed
    cfg.device = 'cpu'

    out_root = Path(args.output_dir) if args.output_dir else None
    if out_root is not None:
        out_root.mkdir(parents=True, exist_ok=True)
    summary: dict = {'ckpts': {}}

    for ckpt_str in args.ckpts:
        ckpt_path = Path(ckpt_str)
        label = _ckpt_label(ckpt_path)
        print(f'[ckpt-eval] {label}: {ckpt_path}')
        agent = build_agent(cfg, ckpt_path)

        if not args.record_replays:
            evaluator = build_evaluator(cfg)
            t = time.perf_counter()
            results = evaluator.run_once(agent)
            wall = time.perf_counter() - t
            per_baseline = {}
            for name, r in results.items():
                per_baseline[name] = {
                    'wp_mean': r.wp_mean,
                    'wp_swap_p0': r.wp_swap_p0,
                    'wp_swap_p1': r.wp_swap_p1,
                    'n_games': r.n_games,
                    'ci95_lo': r.ci95_lo,
                    'ci95_hi': r.ci95_hi,
                }
                print(f'  {name:<35} wp={r.wp_mean:.3f} ci95=[{r.ci95_lo:.3f},{r.ci95_hi:.3f}]')
            summary['ckpts'][label] = {'wall_s': round(wall, 2), 'baselines': per_baseline}
            evaluator.close()
        else:
            from tools.eval._replay_runner import dump_replays_for_ckpt

            ck_out = (out_root / label) if out_root else Path(f'/tmp/eval_{label}')
            ck_out.mkdir(parents=True, exist_ok=True)
            dump_replays_for_ckpt(
                cfg=cfg,
                agent=agent,
                ckpt_label=label,
                baselines=args.baselines,
                output_dir=ck_out,
                save_both_win=args.save_both_win,
                only_sid=args.only_sid,
                scenarios_seed=args.scenarios_seed,
                paradigm=args.paradigm,
            )

    if out_root and summary['ckpts']:
        (out_root / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
