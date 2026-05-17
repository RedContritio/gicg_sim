"""Pull Windows → Mac. Selective rsync of artifacts/<run>/ — only
metrics.jsonl + summary.json + latest.pt + tb/(skip per-step ckpts unless
--all-ckpts).

Usage::

    .venv/bin/python -m tools.remote.pull <run-label>
    .venv/bin/python -m tools.remote.pull <run-label> --all-ckpts
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.remote._common import REMOTE


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run_label', type=str)
    p.add_argument('--remote-root', default='D:/gicg_dev/artifacts')
    p.add_argument('--local-root', default='artifacts')
    p.add_argument('--all-ckpts', action='store_true', help='also pull ckpt_*.pt')
    args = p.parse_args()

    src = f'{REMOTE}:{args.remote_root}/{args.run_label}/'
    dst = Path(args.local_root) / args.run_label
    dst.mkdir(parents=True, exist_ok=True)
    includes = [
        '--include=latest.pt',
        '--include=metrics.jsonl',
        '--include=summary.json',
        '--include=eval_metrics.jsonl',
        '--include=tb/',
        '--include=tb/*',
    ]
    if args.all_ckpts:
        includes.append('--include=ckpt_*.pt')
    includes.append('--exclude=*')
    cmd = ['rsync', '-az', '--partial', '--inplace', *includes, src, f'{dst}/']
    print(f'[pull] {src} -> {dst}')
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
