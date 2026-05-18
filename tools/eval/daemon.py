"""DMC eval daemon — Mac side asynchronous eval, pulls ckpt from Windows
GPU training box and runs PeriodicEvaluator.

架构 (review C.3 / C.4 / E.2 一举三得):
  Windows training: 只 save ckpt + 不再调 in-process eval(cfg.eval.enabled=False)
  Mac eval daemon:  poll ckpts/latest.pt mtime → rsync 拉 → load → 跑 eval → 写 mac 本地 metrics + TB

不回传 train 端;Mac 上同 artifacts/<run>/ 目录里既有 train 的 metrics.jsonl(也通过 rsync 同步)
也有 daemon 写的 eval_metrics.jsonl + eval_tb/, user 在 Mac 上 tensorboard 看 train + eval 双轴。

Usage::

    .venv/bin/python -m tools.eval.daemon configs/dmc_stage3.toml \\
        --run-label dmc_stage3_pilot \\
        --remote dev@192.168.31.56:D:/gicg_dev/artifacts \\
        --poll-seconds 30

每 ``--poll-seconds`` 秒一轮:
  1. rsync 拉 artifacts/<run-label>/  (含 ckpts/latest.pt, ckpts/ckpt_*.pt, metrics.jsonl, tb/)
  2. 比 local ckpts/latest.pt mtime;无变化 → continue
  3. mtime 变 → 解析 ckpt frame# → 构造独立 inference DmcAgent → 跑 PeriodicEvaluator → log

退出: ctrl-c 或 `--max-iterations N`。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


def _do_rsync(remote: str, local_root: Path, run_label: str) -> int:
    """rsync from remote artifacts/<run-label>/ to local <local_root>/<run-label>/.

    Returns rsync exit code; 0 = success, non-zero = transient failure
    (network, ckpt being written) we log + continue."""
    src = f'{remote}/{run_label}/'
    dst = local_root / run_label
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        'rsync',
        '-az',
        '--partial',
        '--inplace',
        # ckpts/(latest.pt + ckpt_*.pt + gauntlet_g*.pt) + metrics.jsonl + tb events
        # T-06 clean-slate:所有 .pt 进 ckpts/ 子目录,rsync include 必须含 ckpts/ 自身
        # 才能让其下文件被 transfer(否则 --exclude=* 会先拒目录)
        '--include=ckpts/',
        '--include=ckpts/***',
        '--include=metrics.jsonl',
        '--include=summary.json',
        '--include=tb/',
        '--include=tb/*',
        '--exclude=*',
        src,
        str(dst) + '/',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f'[daemon] rsync exit={result.returncode}: {result.stderr.strip()[:300]}', file=sys.stderr)
    return result.returncode


def _ckpt_frame(ckpt_path: Path, paradigm: str = 'dmc') -> Optional[int]:
    """Read TrainState.frames from ckpt blob via paradigm adapter."""
    from tools.eval._paradigm import resolve

    return resolve(paradigm, 'ckpt_frame')(ckpt_path)


def _build_eval_agent_from_ckpt(cfg, ckpt_path: Path, paradigm: str = 'dmc'):
    """Construct an independent inference agent via paradigm adapter."""
    from tools.eval._paradigm import resolve

    return resolve(paradigm, 'build_agent')(cfg, ckpt_path)


def _run_one_eval(
    cfg, local_run_dir: Path, frame: int, evaluator, eval_writer, jsonl_fh, paradigm: str = 'dmc'
) -> None:
    """Run one eval round + write metrics + TB."""
    t = time.perf_counter()
    ckpt_path = local_run_dir / 'ckpts' / 'latest.pt'
    agent = _build_eval_agent_from_ckpt(cfg, ckpt_path, paradigm)
    results = evaluator.run_once(agent)
    eval_wall = time.perf_counter() - t

    payload = {
        'kind': 'eval',
        'frame': frame,
        'eval_wall_s': round(eval_wall, 2),
        'ts': datetime.now().isoformat(timespec='seconds'),
    }
    for name, r in results.items():
        payload[f'vs_{name}'] = {
            'wp_mean': r.wp_mean,
            'wp_swap_p0': r.wp_swap_p0,
            'wp_swap_p1': r.wp_swap_p1,
            'n_games': r.n_games,
            'ci95_lo': r.ci95_lo,
            'ci95_hi': r.ci95_hi,
        }
        if eval_writer is not None:
            eval_writer.add_scalar(f'eval/{name}_wp_mean', r.wp_mean, frame)
            eval_writer.add_scalar(f'eval/{name}_wp_swap_p0', r.wp_swap_p0, frame)
            eval_writer.add_scalar(f'eval/{name}_wp_swap_p1', r.wp_swap_p1, frame)
            eval_writer.add_scalar(f'eval/{name}_ci95_width', r.ci95_hi - r.ci95_lo, frame)
    print(f'[eval] {payload}')
    if jsonl_fh is not None:
        jsonl_fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
        jsonl_fh.flush()
    if eval_writer is not None:
        eval_writer.flush()


def main():
    p = argparse.ArgumentParser(description='DMC Mac eval daemon')
    p.add_argument('--paradigm', default='dmc', help='paradigm key (default: dmc)')
    p.add_argument('config', type=str, help='TOML config(daemon 用 cfg.scenario + cfg.eval 配 evaluator)')
    p.add_argument('--run-label', required=True, type=str, help='Windows artifacts dir name(<ts>_<label>)')
    p.add_argument(
        '--remote', required=True, type=str, help='rsync source root, e.g. dev@192.168.31.56:D:/gicg_dev/artifacts'
    )
    p.add_argument('--local-artifacts-root', type=str, default='artifacts')
    p.add_argument('--poll-seconds', type=int, default=30)
    p.add_argument('--max-iterations', type=int, default=0, help='0 = forever')
    p.add_argument('--data-dir', type=str, default='data')
    args = p.parse_args()

    # CPU optim
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')

    from tools.eval._paradigm import resolve

    load_config = resolve(args.paradigm, 'load_config')
    build_evaluator = resolve(args.paradigm, 'build_evaluator')

    try:
        from torch.utils.tensorboard import SummaryWriter
    except ImportError:
        SummaryWriter = None  # type: ignore

    cfg = load_config(args.config, data_dir=args.data_dir)
    # daemon 复用 cfg.scenario + cfg.eval 构 evaluator(scenarios 由 cfg.eval.scenarios_seed 决定 deterministic)
    evaluator = build_evaluator(cfg)

    local_root = Path(args.local_artifacts_root).resolve()
    local_run_dir = local_root / args.run_label
    local_run_dir.mkdir(parents=True, exist_ok=True)

    eval_jsonl = local_run_dir / 'eval_metrics.jsonl'
    jsonl_fh = open(eval_jsonl, 'a', encoding='utf-8')
    eval_writer = SummaryWriter(log_dir=str(local_run_dir / 'eval_tb')) if SummaryWriter is not None else None

    last_eval_mtime: Optional[float] = None
    iteration = 0
    print(f'[daemon] watching {args.remote}/{args.run_label}/ → {local_run_dir}, poll={args.poll_seconds}s')

    try:
        while True:
            iteration += 1
            t0 = time.perf_counter()

            rc = _do_rsync(args.remote, local_root, args.run_label)
            if rc != 0:
                print(f'[daemon] iter {iteration}: rsync failed, sleep + retry')
                time.sleep(args.poll_seconds)
                if args.max_iterations and iteration >= args.max_iterations:
                    break
                continue

            latest = local_run_dir / 'ckpts' / 'latest.pt'
            if not latest.exists():
                print(f'[daemon] iter {iteration}: no ckpts/latest.pt yet,sleep')
            else:
                mtime = latest.stat().st_mtime
                if last_eval_mtime is None or mtime > last_eval_mtime:
                    frame = _ckpt_frame(latest, args.paradigm) or 0
                    print(f'[daemon] iter {iteration}: new ckpt mtime={mtime} frame={frame}, running eval...')
                    try:
                        _run_one_eval(cfg, local_run_dir, frame, evaluator, eval_writer, jsonl_fh, args.paradigm)
                        last_eval_mtime = mtime
                    except Exception as e:
                        print(f'[daemon] eval failed: {type(e).__name__}: {e}', file=sys.stderr)
                else:
                    print(f'[daemon] iter {iteration}: no new ckpt (mtime unchanged)')

            if args.max_iterations and iteration >= args.max_iterations:
                break

            dt = time.perf_counter() - t0
            sleep_left = max(1.0, args.poll_seconds - dt)
            time.sleep(sleep_left)
    except KeyboardInterrupt:
        print('[daemon] interrupted, exit clean')
    finally:
        jsonl_fh.close()
        if eval_writer is not None:
            eval_writer.close()
        evaluator.close()


if __name__ == '__main__':
    sys.exit(main())
