"""Quick status check for training on remote GPU box — cfg-driven dispatch。

CLI:

    .venv/bin/python -m tools.runs.status <cfg.toml> [--watch --interval N --run NAME]

cfg ``[meta].host`` decides local vs remote。Reads
``artifacts/<latest-run>/metrics.jsonl`` over ssh + ``status.ps1`` (assumed
synced to remote at ``<remote.root>/tools/runs/status.ps1``)。Shows GPU
util/mem,Python proc CPU time,latest eval/train/episode rows + fps。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg


def ssh_query(remote: RemoteCfg, run_label: str = '') -> str:
    """Run the PS script over ssh, return stdout."""
    sep = '\\' if remote.os == 'windows' else '/'
    ps_script_path = f'{remote.root_native}{sep}tools{sep}runs{sep}status.ps1'
    arg = f' -RunName {run_label}' if run_label else ''
    cmd = [
        'ssh',
        remote.ssh,
        f'powershell -ExecutionPolicy Bypass -File {ps_script_path}{arg}',
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            errors='replace',  # Windows stderr may emit cp936 zh-CN errors
        )
    except subprocess.TimeoutExpired:
        return '[ssh timeout]'
    if result.returncode != 0:
        return f'[ssh exit={result.returncode}: {result.stderr[:200]}]'
    return result.stdout


def parse_and_format(raw: str, debug: bool = False) -> str:
    if debug:
        print('--- raw output ---')
        print(raw)
        print('--- end raw ---')
    """Parse PS script output sections + tail metrics.jsonl, format human-readable."""
    sections = {}
    cur = None
    cur_lines: list = []
    run_name = '?'
    for line in raw.splitlines():
        if line.startswith('===RUN==='):
            run_name = line[len('===RUN===') :].strip()
            continue
        if line.startswith('===') and line.endswith('==='):
            if cur:
                sections[cur] = '\n'.join(cur_lines).strip()
            cur = line.strip('=')
            cur_lines = []
            continue
        cur_lines.append(line)
    if cur:
        sections[cur] = '\n'.join(cur_lines).strip()

    out = []
    out.append(f'== run: {run_name} ==')

    gpu = sections.get('GPU', '')
    if gpu:
        out.append(f'GPU:  {gpu.split(chr(10))[0].strip()}')
    cpu = sections.get('CPU', '')
    if cpu:
        out.append(f'CPU:  {cpu.strip()}')
    mem = sections.get('MEM', '')
    if mem:
        out.append(f'MEM:  {mem.strip()}')

    proc = sections.get('PROC', '')
    if proc:
        out.append('python procs:')
        for ln in proc.splitlines():
            out.append(f'  {ln}')

    metrics_raw = sections.get('METRICS', '')
    if not metrics_raw:
        out.append('(no metrics.jsonl)')
        return '\n'.join(out)

    lines = [ln for ln in metrics_raw.splitlines() if ln.strip()]
    last_ep = None
    last_eval = None
    last_train = None
    last_mp_status = None
    first_ep_wall = None
    first_ep_frames = None
    for ln in lines:
        try:
            d = json.loads(ln)
        except Exception:
            continue
        k = d.get('kind')
        if k == 'episode':
            if first_ep_wall is None:
                first_ep_wall, first_ep_frames = d.get('wall_s'), d.get('frames')
            last_ep = d
        elif k == 'eval':
            last_eval = d
        elif k == 'train_step':
            last_train = d
        elif k == 'mp_status':
            last_mp_status = d

    if last_ep:
        frames = last_ep.get('frames', 0)
        wall = last_ep.get('wall_s', 0)
        ep = last_ep.get('ep', 0)
        fps_window = ''
        if first_ep_wall and wall > first_ep_wall:
            df = frames - first_ep_frames
            dt = wall - first_ep_wall
            if dt > 0:
                fps_window = f' / fps(window)={df / dt:.2f}'
        out.append(f'episode: ep={ep} frames={frames} wall={wall}s{fps_window}')
    if last_mp_status:
        out.append(
            f'mp_status: frames={last_mp_status.get("frames")} '
            f'eps={last_mp_status.get("episodes")} '
            f'train_steps={last_mp_status.get("train_steps")} '
            f'buf={last_mp_status.get("buf")} W/L/D={last_mp_status.get("wins")}/'
            f'{last_mp_status.get("losses")}/{last_mp_status.get("draws")}'
        )
    if last_train:
        out.append(f'train: step={last_train.get("step")} loss={last_train.get("loss", 0):.3f}')
    if last_eval:
        ev = ['eval @ frames=' + str(last_eval.get('frames'))]
        for k, v in last_eval.items():
            if isinstance(v, dict) and 'wp_mean' in v:
                ev.append(f'{k}={v["wp_mean"]:.3f}')
        out.append(' '.join(ev))

    return '\n'.join(out)


def _run_local(args) -> int:
    """Local mode — currently delegates to direct file read of latest run.
    For now, just emit a hint(production usage is remote-only)。"""
    sys.stderr.write(
        '[status] local mode not implemented — use `tools.runs.list` + `tools.runs.show <NNN>` for local inspection.\n'
    )
    return 1


def _run_remote(remote: RemoteCfg, args) -> int:
    while True:
        ts = datetime.now().strftime('%H:%M:%S')
        raw = ssh_query(remote, args.run)
        formatted = parse_and_format(raw, debug=args.debug)
        if args.watch:
            print(f'\n[{ts}]')
            print(formatted)
            print(f'(next refresh in {args.interval}s, ctrl-c to stop)')
            time.sleep(args.interval)
        else:
            print(f'[{ts}]')
            print(formatted)
            return 0


def main():
    p = argparse.ArgumentParser(description='Training status quick-check (cfg-driven local/remote)')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('--watch', action='store_true', help='loop every --interval seconds')
    p.add_argument('--interval', type=int, default=30)
    p.add_argument('--run', type=str, default='', help='specific run dir name (default: latest)')
    p.add_argument('--debug', action='store_true', help='print raw ssh output')
    args = p.parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    return _run_remote(remote, args)


if __name__ == '__main__':
    sys.exit(main())
