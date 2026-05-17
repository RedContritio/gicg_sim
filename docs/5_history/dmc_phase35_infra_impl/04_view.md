# Phase D · 看结果工具 + 周用工具(Task 11-12)

> 父索引:`README.md`。Task 11 → 12 顺序。低频次工具,不阻塞主训练。

---

## Task 11: `tools/eval/metrics_view.py` + `tools/eval/compare.py`

**Files:**
- Create: `tools/eval/metrics_view.py`
- Create: `tools/eval/compare.py`

- [ ] **Step 1: 写 `tools/eval/metrics_view.py`**

```python
"""Quick view of artifacts/<run>/metrics.jsonl — last eval per baseline,
fps window(early vs late),loss/grad_norm trend + NaN/inf flag,episode count。

Usage::

    .venv/bin/python -m tools.eval.metrics_view artifacts/<run>/
    .venv/bin/python -m tools.eval.metrics_view artifacts/<run>/ --tail 20
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run_dir', type=str)
    p.add_argument('--tail', type=int, default=10, help='train_step rows to print')
    args = p.parse_args()

    run = Path(args.run_dir)
    metrics = run / 'metrics.jsonl'
    if not metrics.exists():
        print(f'[metrics_view] not found: {metrics}', file=sys.stderr)
        return 1

    eps: list[dict] = []
    trains: list[dict] = []
    evals: list[dict] = []
    summary: dict | None = None
    for ln in metrics.read_text().splitlines():
        try:
            d = json.loads(ln)
        except Exception:
            continue
        k = d.get('kind')
        if k == 'episode':
            eps.append(d)
        elif k == 'train_step':
            trains.append(d)
        elif k == 'eval':
            evals.append(d)
        elif k == 'final':
            summary = d

    print(f'== {run.name} ==')
    if eps:
        ep0, epN = eps[0], eps[-1]
        df = epN.get('frames', 0) - ep0.get('frames', 0)
        dt = epN.get('wall_s', 0) - ep0.get('wall_s', 0)
        fps = df / dt if dt > 0 else float('nan')
        print(f'episodes: {len(eps)}, last frames={epN.get("frames")}, fps={fps:.2f}')
        n_half = len(eps) // 2 or 1
        if n_half >= 5:
            early, late = eps[:n_half], eps[n_half:]
            de_w = early[-1]['wall_s'] - early[0]['wall_s']
            dl_w = late[-1]['wall_s'] - late[0]['wall_s']
            fps_e = (early[-1]['frames'] - early[0]['frames']) / de_w if de_w > 0 else float('nan')
            fps_l = (late[-1]['frames'] - late[0]['frames']) / dl_w if dl_w > 0 else float('nan')
            print(f'  fps early/late: {fps_e:.2f} / {fps_l:.2f}')

    if trains:
        last = trains[-args.tail:]
        if any(not math.isfinite(t.get('loss', 0)) for t in trains):
            print(f'⚠ train: NaN/inf loss detected in {len(trains)} steps')
        print(f'train_steps (last {len(last)}):')
        for t in last:
            print(f'  step={t.get("step")} frames={t.get("frames")} loss={t.get("loss"):.4f}')

    if evals:
        last_e = evals[-1]
        print(f'last eval @ frames={last_e.get("frames")}:')
        for k, v in last_e.items():
            if isinstance(v, dict) and 'wp_mean' in v:
                w = v.get('ci95_hi', 0) - v.get('ci95_lo', 0)
                print(f'  {k}: wp={v["wp_mean"]:.3f} ci95±{w/2:.3f}')

    if summary:
        print(f'FINAL: frames={summary.get("frames")} wall_s={summary.get("wall_s")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 写 `tools/eval/compare.py`**

```python
"""Compare multiple eval JSON outputs (from tools.eval.ckpt) as markdown
table。Useful for ablation runs / staged ckpt comparisons。

Usage::

    .venv/bin/python -m tools.eval.compare /tmp/cmp/summary.json
    .venv/bin/python -m tools.eval.compare a.json b.json c.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('jsons', nargs='+', type=str)
    args = p.parse_args()

    rows: dict[str, dict[str, float]] = {}
    cis: dict[str, dict[str, float]] = {}
    all_baselines: set[str] = set()
    for j in args.jsons:
        blob = json.loads(Path(j).read_text())
        # Either tools.eval.ckpt summary form {'ckpts': {label: {'baselines': {...}}}}
        # or legacy single-ckpt form {'ckpt': ..., 'baselines': {...}}
        ckpts_dict = blob.get('ckpts') or {Path(j).stem: {'baselines': blob.get('baselines', {})}}
        for label, payload in ckpts_dict.items():
            rows.setdefault(label, {})
            cis.setdefault(label, {})
            for bn, m in payload.get('baselines', {}).items():
                rows[label][bn] = m['wp_mean']
                cis[label][bn] = (m['ci95_hi'] - m['ci95_lo']) / 2
                all_baselines.add(bn)

    bls = sorted(all_baselines)
    print('| ckpt | ' + ' | '.join(bls) + ' |')
    print('|---|' + '|'.join(['---'] * len(bls)) + '|')
    for label in sorted(rows):
        cells = []
        for bn in bls:
            if bn in rows[label]:
                cells.append(f'{rows[label][bn]:.3f} ±{cis[label][bn]:.3f}')
            else:
                cells.append('—')
        print(f'| {label} | ' + ' | '.join(cells) + ' |')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 3: Smoke 两个 view**

Run:
```bash
.venv/bin/python -m tools.eval.metrics_view artifacts/<SMOKE_RUN>
.venv/bin/python -m tools.eval.compare /tmp/eval_smoke/summary.json
```
Expected: 各打印解析后的表格,exit 0。

- [ ] **Step 4: Commit**

```bash
git add tools/eval/metrics_view.py tools/eval/compare.py
git commit -m "tools/eval: add metrics_view (parse metrics.jsonl) + compare (markdown ckpt-vs-baseline grid)"
```

---

## Task 12: `tools/remote/pull.py` + `tools/remote/build_engine.py`

**Files:**
- Create: `tools/remote/pull.py`
- Create: `tools/remote/build_engine.py`

- [ ] **Step 1: 写 `tools/remote/pull.py`**

```python
"""Pull Windows → Mac. Selective rsync of artifacts/<run>/ — only
metrics.jsonl + summary.json + latest.pt + tb/(skip per-step ckpts unless
--all-ckpts)。

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
        '--include=latest.pt', '--include=metrics.jsonl',
        '--include=summary.json', '--include=eval_metrics.jsonl',
        '--include=tb/', '--include=tb/*',
    ]
    if args.all_ckpts:
        includes.append('--include=ckpt_*.pt')
    includes.append('--exclude=*')
    cmd = ['rsync', '-az', '--partial', '--inplace', *includes, src, f'{dst}/']
    print(f'[pull] {src} → {dst}')
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 写 `tools/remote/build_engine.py`**

```python
"""Build libgicg.dll on Windows GPU box(cgo c-shared)。CGO_ENABLED=1 +
CC=gcc(MSYS)+ PATH 含 MSYS bin。Output → D:\\gicg_dev\\gicg_env\\libgicg.dll。

Usage::

    .venv/bin/python -m tools.remote.build_engine
"""

from __future__ import annotations

import sys

from tools.remote._common import REMOTE_ROOT_WIN, ssh_run

PS = (
    '$env:CGO_ENABLED=1; $env:CC="gcc"; '
    '$env:PATH="C:\\msys64\\mingw64\\bin;" + $env:PATH; '
    f'cd "{REMOTE_ROOT_WIN}"; '
    'go build -buildmode=c-shared -o gicg_env\\libgicg.dll .\\gicg_engine\\capi\\'
)


def main():
    print('[build_engine] cgo build libgicg.dll on Windows...')
    r = ssh_run(PS, timeout=300)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 3: Smoke**

Run: `.venv/bin/python -m tools.remote.build_engine`
Expected: Windows 端 go build 成功,libgicg.dll 更新;exit 0。

如果 MSYS PATH 不对或 CGO 找不到 gcc,改 `PS` 里的路径常量到当前 Windows 实际位置;build_engine.py 顶部加 comment 注明常用 MSYS 安装路径。

- [ ] **Step 4: 全 pytest no regression**

Run: `.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q`
Expected: 全 pass(含 Task 6 新增 `test_dmc_nan_guard`)。

- [ ] **Step 5: Commit**

```bash
git add tools/remote/pull.py tools/remote/build_engine.py
git commit -m "tools/remote: add pull.py (artifacts rsync) + build_engine.py (cgo libgicg.dll)"
```

---

## 最终验收

回 `README.md` 验收 checklist,逐项确认。
