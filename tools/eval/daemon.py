"""DMC eval daemon — Mac side asynchronous eval, pulls ckpt from Windows
GPU training box and runs PeriodicEvaluator.

架构 (review C.3 / C.4 / E.2 一举三得):
  Windows training: 只 save ckpt + 不再调 in-process eval(cfg.eval.enabled=False)
  Mac eval daemon:  poll ckpts/latest.pt mtime → scp 拉 → load → 跑 eval → 写 mac 本地 metrics + TB

不回传 train 端;daemon 写 eval_metrics.jsonl + eval_tb/, user 在 Mac 上 tensorboard
看 eval 曲线。

Usage::

    .venv/bin/python -m tools.eval.daemon configs/dmc/stage3_pilot.toml \\
        --run-label dmc_stage3_pilot \\
        --poll-seconds 30

每 ``--poll-seconds`` 秒一轮:
  1. 按 cfg 的 [meta].host 决定本地或远端;远端只拉 artifacts/<run-label>/ckpts/latest.pt
  2. 比 local ckpts/latest.pt mtime;无变化 → continue
  3. mtime 变 → 解析 ckpt frame# → 构造独立 inference DmcAgent → 跑 PeriodicEvaluator → log

退出: ctrl-c 或 `--max-iterations N`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg, scp_from


def _pull_latest(remote: RemoteCfg | None, local_run_dir: Path, run_label: str) -> int:
    """Fetch ``artifacts/<run-label>/ckpts/latest.pt`` with cfg-driven dispatch."""
    if is_local_host(remote):
        return 0
    assert remote is not None
    ckpt_dir = local_run_dir / 'ckpts'
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    latest = ckpt_dir / 'latest.pt'
    remote_rel = f'artifacts/{run_label}/ckpts/latest.pt'
    with tempfile.NamedTemporaryFile(prefix='.latest.', suffix='.pt', dir=ckpt_dir, delete=False) as fh:
        temp_path = Path(fh.name)
    try:
        result = scp_from(remote, remote_rel, temp_path, timeout=300, preserve=True)
        if result.returncode != 0:
            print(f'[daemon] scp exit={result.returncode}: {result.stderr.strip()[:300]}', file=sys.stderr)
            return result.returncode
        os.replace(temp_path, latest)
        return 0
    finally:
        temp_path.unlink(missing_ok=True)


def _ckpt_frame(ckpt_path: Path, paradigm: str = 'dmc') -> Optional[int]:
    """Read TrainState.frames from ckpt blob via paradigm adapter."""
    from tools.eval._paradigm import resolve

    return resolve(paradigm, 'ckpt_frame')(ckpt_path)


def _build_eval_agent_from_ckpt(cfg, ckpt_path: Path, paradigm: str = 'dmc'):
    """Construct an independent inference agent via paradigm adapter."""
    from tools.eval._paradigm import resolve

    return resolve(paradigm, 'build_agent')(cfg, ckpt_path)


def _build_random_agent(cfg, paradigm: str = 'dmc'):
    """Sanity baseline: ε=1.0 uniform-random agent via paradigm adapter (no ckpt load)。"""
    from tools.eval._paradigm import resolve

    return resolve(paradigm, 'build_random_agent')(cfg)


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
    p.add_argument('--local-artifacts-root', type=str, default='artifacts')
    p.add_argument('--poll-seconds', type=int, default=30)
    p.add_argument('--max-iterations', type=int, default=0, help='0 = forever')
    p.add_argument('--data-dir', type=str, default='data')
    p.add_argument(
        '--random-agent',
        action='store_true',
        help='Sanity: skip ckpt load + use ε=1.0 uniform-random agent. 一次性 (max-iterations=1) 跑 + '
        '与 ckpt eval 对比 (期望 random agent vs F1-D2 wp ≥ 0.05-0.20;若 ≈ 0 则 eval pipeline 结构问题)。',
    )
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
    remote = load_remote_from_cfg(Path(args.config))

    local_root = Path(args.local_artifacts_root).resolve()
    local_run_dir = local_root / args.run_label
    local_run_dir.mkdir(parents=True, exist_ok=True)

    eval_jsonl = local_run_dir / 'eval_metrics.jsonl'
    jsonl_fh = open(eval_jsonl, 'a', encoding='utf-8')
    eval_writer = SummaryWriter(log_dir=str(local_run_dir / 'eval_tb')) if SummaryWriter is not None else None

    last_eval_mtime: Optional[float] = None
    iteration = 0
    source = remote.ssh if remote is not None and not is_local_host(remote) else 'local'
    print(f'[daemon] watching {source}:artifacts/{args.run_label}/ → {local_run_dir}, poll={args.poll_seconds}s')

    try:
        while True:
            iteration += 1
            t0 = time.perf_counter()

            rc = _pull_latest(remote, local_run_dir, args.run_label)
            latest_path = local_run_dir / 'ckpts' / 'latest.pt'
            if rc != 0:
                if latest_path.exists():
                    print(f'[daemon] iter {iteration}: scp failed but local ckpts/latest.pt exists — proceed with eval')
                else:
                    print(f'[daemon] iter {iteration}: scp failed + no local ckpt, sleep + retry')
                    time.sleep(args.poll_seconds)
                    if args.max_iterations and iteration >= args.max_iterations:
                        break
                    continue

            latest = latest_path
            if args.random_agent:
                # Sanity mode: 直接 build random agent + run eval, 绕 ckpt mtime check。
                print(f'[daemon] iter {iteration}: random-agent sanity mode, building ε=1.0 uniform agent...')
                try:
                    agent = _build_random_agent(cfg, args.paradigm)
                    t = time.perf_counter()
                    results = evaluator.run_once(agent)
                    wall = time.perf_counter() - t
                    payload = {
                        'kind': 'eval',
                        'frame': 0,
                        'eval_wall_s': round(wall, 2),
                        'ts': datetime.now().isoformat(timespec='seconds'),
                        'agent': 'random_epsilon1',
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
                    print(f'[eval-random] {payload}')
                    if jsonl_fh is not None:
                        jsonl_fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
                        jsonl_fh.flush()
                except Exception as e:
                    print(f'[daemon] random-agent eval failed: {type(e).__name__}: {e}', file=sys.stderr)
            elif not latest.exists():
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
