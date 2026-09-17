"""Quick status check for a remote training host.

CLI:

    .venv/bin/python -m tools.runs.status <cfg.toml> [--watch --interval N --run NAME]

The command invokes ``tools/runs/status.ps1`` on Windows and an equivalent
shell probe on POSIX over SSH, then formats GPU, process, memory, and recent
training metrics. Local configs print a pointer to ``tools.runs.list`` and
``tools.runs.show`` instead.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    ssh_run,
    ssh_run_bash,
)


def _build_ps(remote: RemoteCfg, run_label: str = '') -> str:
    """Build the Windows status probe."""
    script_path = f'{remote.root_native}\\tools\\runs\\status.ps1'
    arg = f' -RunName {ps_quote(run_label)}' if run_label else ''
    return f'& {ps_quote(script_path)}{arg}'


def _build_sh(remote: RemoteCfg, run_label: str = '') -> str:
    """Build a POSIX status probe with the same section contract as status.ps1."""
    lines = [
        f'root={shlex.quote(remote.root)}',
        'artifacts="$root/artifacts"',
        "latest=''",
        f'if [ -n {shlex.quote(run_label)} ]; then',
        '  for d in "$artifacts"/*/; do',
        '    [ -d "$d" ] || continue',
        '    d=${d%/}',
        f'    if [ "${{d##*/}}" = {shlex.quote(run_label)} ]; then latest="$d"; break; fi',
        '  done',
        'fi',
        'if [ -z "$latest" ]; then',
        '  for d in "$artifacts"/*/; do',
        '    [ -d "$d" ] || continue',
        '    d=${d%/}',
        '    if [ -z "$latest" ] || [ "$d" -nt "$latest" ]; then latest="$d"; fi',
        '  done',
        'fi',
        'if [ -n "$latest" ]; then echo "===RUN===${latest##*/}"; else echo "===RUN===(none)"; fi',
        "echo '===GPU==='",
        'nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader 2>/dev/null || true',
        "echo '===MEM==='",
        'if command -v free >/dev/null 2>&1; then',
        '  free -m | awk \'/^Mem:/ {printf "mem_used=%dMB total=%dMB pct=%.1f%%\\n", $3, $2, ($2 ? $3*100/$2 : 0)}\'',
        'elif command -v sysctl >/dev/null 2>&1; then',
        '  total=$(sysctl -n hw.memsize 2>/dev/null)',
        '  page=$(sysctl -n hw.pagesize 2>/dev/null)',
        '  if [ -n "$total" ] && [ -n "$page" ] && [ "$page" -gt 0 ] 2>/dev/null; then',
        '    pages=$(vm_stat 2>/dev/null | awk \'/Pages free/ {gsub(/\\./,"",$3); f=$3} /Pages inactive/ {gsub(/\\./,"",$3); i=$3} /Pages speculative/ {gsub(/\\./,"",$3); s=$3} END {print f+i+s}\')',
        '    if [ -n "$pages" ]; then',
        '      used_bytes=$((total - pages*page))',
        '      awk -v u="$used_bytes" -v t="$total" \'BEGIN {printf "mem_used=%dMB total=%dMB pct=%.1f%%\\n", u/1048576, t/1048576, u*100/t}\'',
        '    else echo mem_unavailable; fi',
        '  else echo mem_unavailable; fi',
        'else echo mem_unavailable; fi',
        "echo '===CPU==='",
        'cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 1)',
        'cpu=$(ps -A -o %cpu= 2>/dev/null | awk -v c="$cores" \'{s+=$1} END {p=(c>0?s/c:0); if(p>100)p=100; printf "%.1f", p}\')',
        'echo "cpu_pct=${cpu:-0}% cores=${cores:-1}"',
        "echo '===PROC==='",
        'ps -eo pid=,comm=,time=,rss= 2>/dev/null | awk \'{c=$2; sub(/^.*\\//,"",c); if (tolower(c) ~ /^python([0-9.]*)?$/) printf "python pid=%s cpu_s=%s ws_mb=%.1f\\n", $1, $3, $4/1024}\'',
        "echo '===METRICS==='",
        'if [ -n "$latest" ] && [ -f "$latest/metrics.jsonl" ]; then tail -n 30 "$latest/metrics.jsonl"; fi',
        'exit 0',
    ]
    return '\n'.join(lines)


def ssh_query(remote: RemoteCfg, run_label: str = '') -> str:
    """Run the OS-specific status probe over ssh, return stdout."""
    if remote.os == 'windows':
        script = _build_ps(remote, run_label)
        runner = ssh_run
    else:
        script = _build_sh(remote, run_label)
        runner = ssh_run_bash
    try:
        result = runner(remote, script, timeout=30)
    except subprocess.TimeoutExpired:
        return '[ssh timeout]'
    if result.returncode != 0:
        return f'[ssh exit={result.returncode}: {result.stderr[:200]}]'
    return result.stdout


def parse_and_format(raw: str, debug: bool = False) -> str:
    """Parse status-script sections and format recent metrics."""
    if debug:
        print('--- raw output ---')
        print(raw)
        print('--- end raw ---')
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
    """Emit the supported local inspection commands."""
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
