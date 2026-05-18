"""Pull Windows → Mac. Selective rsync of artifacts/<run>/ — only
metrics.jsonl + summary.json + ckpts/latest.pt + tb/(skip per-step
ckpts unless --all-ckpts).

T-06 clean-slate:所有 .pt 进 ``<run>/ckpts/`` 子目录,rsync include
模式必须含 ``ckpts/`` 自身才能让其下文件被 transfer(否则 --exclude=*
会先拒目录)。

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
    p.add_argument('--all-ckpts', action='store_true', help='also pull ckpts/ckpt_*.pt + gauntlet_*.pt')
    args = p.parse_args()

    src = f'{REMOTE}:{args.remote_root}/{args.run_label}/'
    dst = Path(args.local_root) / args.run_label
    dst.mkdir(parents=True, exist_ok=True)
    # T-06 layout:.pt 在 <run>/ckpts/ 下,rsync 必须先 include 目录自身。
    # 默认只拉 ckpts/latest.pt,--all-ckpts 全量(ckpt_*.pt + gauntlet_*.pt)。
    includes = [
        '--include=ckpts/',
        '--include=ckpts/latest.pt',
        '--include=metrics.jsonl',
        '--include=summary.json',
        '--include=eval_metrics.jsonl',
        '--include=tb/',
        '--include=tb/*',
    ]
    if args.all_ckpts:
        # ckpts/*** 递归含所有 .pt(ckpt_<step>.pt + gauntlet_g<g>.pt)
        includes.append('--include=ckpts/***')
    includes.append('--exclude=*')
    cmd = ['rsync', '-az', '--partial', '--inplace', *includes, src, f'{dst}/']
    print(f'[pull] {src} -> {dst}')
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
