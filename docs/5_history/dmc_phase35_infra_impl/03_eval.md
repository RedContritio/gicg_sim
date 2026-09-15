# Phase C · `tools/eval/` paradigm-agnostic 评估栈(Task 8-10)

> 父索引:`README.md`。Task 8 → 9 → 10 顺序;Task 9 依赖 Task 8 完成,Task 10 依赖 Task 8。

---

## Task 8: `tools/eval/_paradigm.py` + `_dmc_adapter.py` — paradigm registry

**Files:**
- Create: `tools/eval/__init__.py`(空)
- Create: `tools/eval/_paradigm.py`
- Create: `tools/eval/_dmc_adapter.py`

- [ ] **Step 1: 建目录**

```bash
mkdir -p tools/eval && : > tools/eval/__init__.py
```

- [ ] **Step 2: 写 `tools/eval/_paradigm.py`**

```python
"""Paradigm registry for tools/eval/. Keeps ckpt.py / daemon.py /
metrics_view.py paradigm-agnostic. Only 'dmc' is populated in this rev;
'az' / 'cfr' entries reserved for future paradigms."""

from __future__ import annotations

from importlib import import_module
from typing import Any

PARADIGMS: dict[str, dict[str, str]] = {
    'dmc': {
        'load_config':     'training.dmc.config_loader:load_config',
        'build_agent':     'tools.eval._dmc_adapter:build_eval_agent',
        'build_evaluator': 'tools.eval._dmc_adapter:build_evaluator',
        'build_baseline':  'tools.eval._dmc_adapter:build_baseline',
        'ckpt_frame':      'tools.eval._dmc_adapter:ckpt_frame',
    },
    # 'az': {...},   # reserved — not implemented this rev
    # 'cfr': {...},  # reserved — not implemented this rev
}


def resolve(paradigm: str, key: str) -> Any:
    """Dynamic-import the function bound to (paradigm, key)."""
    if paradigm not in PARADIGMS:
        raise KeyError(f'unknown paradigm {paradigm!r}; known: {sorted(PARADIGMS)}')
    spec = PARADIGMS[paradigm].get(key)
    if spec is None:
        raise NotImplementedError(f'paradigm {paradigm!r} has no {key!r} adapter')
    mod_name, fn_name = spec.split(':')
    return getattr(import_module(mod_name), fn_name)
```

- [ ] **Step 3: 写 `tools/eval/_dmc_adapter.py`**

```python
"""DMC paradigm adapter — bridges PeriodicEvaluator + DmcAgent + baseline
builder behind the paradigm-agnostic interface in _paradigm.py."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_eval_agent(cfg, ckpt_path: Path):
    """Load DmcAgent in eval mode from ckpt blob。"""
    import torch
    from training.dmc.agent import DmcAgent

    agent = DmcAgent(cfg.agent, device='cpu', lr=cfg.learning_rate, epsilon=0.0)
    blob = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    agent.net.load_state_dict(blob['net'])
    agent.net.eval()
    return agent


def build_evaluator(cfg):
    from training.dmc.eval.periodic_eval import PeriodicEvaluator
    return PeriodicEvaluator(cfg)


def build_baseline(name: str, *, seed: int, cfg):
    from training.dmc.eval.periodic_eval import _build_baseline_player
    return _build_baseline_player(name, seed=seed, dmc_cfg=cfg)


def ckpt_frame(ckpt_path: Path) -> Optional[int]:
    """Read TrainState.frames out of ckpt blob (latest.pt / ckpt_<N>.pt)。"""
    import torch
    try:
        blob = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    except Exception:
        return None
    return (blob.get('state') or {}).get('frames')
```

- [ ] **Step 4: Smoke**

Run: `.venv/bin/python -c "from tools.eval._paradigm import resolve; f=resolve('dmc','load_config'); print(f.__module__)"`
Expected: `training.dmc.config_loader`

- [ ] **Step 5: Commit**

```bash
git add tools/eval/__init__.py tools/eval/_paradigm.py tools/eval/_dmc_adapter.py
git commit -m "tools/eval: paradigm registry + dmc adapter (decouple ckpt.py / daemon.py from training.dmc imports)"
```

---

## Task 9: `tools/eval/ckpt.py` 合并 `dmc_eval_ckpt` + `dmc_dump_replay`

**Files:**
- Create: `tools/eval/ckpt.py`
- Create: `tools/eval/_replay_runner.py`
- Delete: `tools/dmc_eval_ckpt.py`
- Delete: `tools/dmc_dump_replay.py`

- [ ] **Step 1: 写 `tools/eval/ckpt.py`(主 CLI)**

```python
"""Paradigm-agnostic ckpt evaluator + replay dumper. Replaces
dmc_eval_ckpt.py + dmc_dump_replay.py.

Usage::

    # 多 ckpt 同 scenarios deterministic 对比
    .venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_pilot.toml \\
        --ckpts artifacts/A/latest.pt artifacts/B/latest.pt \\
        --baselines random F1-D2 F1-D4 --n-scenarios 128 \\
        --output-dir /tmp/cmp/

    # 出 replay yaml(diff 两 ckpt 策略)
    .venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_pilot.toml \\
        --ckpts a.pt b.pt --baselines F1-D2 \\
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
    """/x/y/202605151019_dmc_stage3_pilot/latest.pt → 202605151019_dmc_stage3_pilot"""
    return p.parent.name


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
    p.add_argument('--save-both-win', action='store_true',
                   help='only record scenarios where ckpt wins both swap-sides vs baseline')
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
                    'wp_swap_p0': r.wp_swap_p0, 'wp_swap_p1': r.wp_swap_p1,
                    'n_games': r.n_games,
                    'ci95_lo': r.ci95_lo, 'ci95_hi': r.ci95_hi,
                }
                print(f'  {name:<35} wp={r.wp_mean:.3f} ci95=[{r.ci95_lo:.3f},{r.ci95_hi:.3f}]')
            summary['ckpts'][label] = {'wall_s': round(wall, 2), 'baselines': per_baseline}
            evaluator.close()
        else:
            from tools.eval._replay_runner import dump_replays_for_ckpt
            ck_out = (out_root / label) if out_root else Path(f'/tmp/eval_{label}')
            ck_out.mkdir(parents=True, exist_ok=True)
            dump_replays_for_ckpt(
                cfg=cfg, agent=agent, ckpt_label=label,
                baselines=args.baselines, output_dir=ck_out,
                save_both_win=args.save_both_win, only_sid=args.only_sid,
                scenarios_seed=args.scenarios_seed, paradigm=args.paradigm,
            )

    if out_root and summary['ckpts']:
        (out_root / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: git mv `dmc_dump_replay.py` → `tools/eval/_replay_runner.py`**

```bash
git rm tools/dmc_eval_ckpt.py
git mv tools/dmc_dump_replay.py tools/eval/_replay_runner.py
```

- [ ] **Step 3: 编辑 `tools/eval/_replay_runner.py`(裁剪 main + 加新函数)**

在迁移后的 `tools/eval/_replay_runner.py` 上做 3 个编辑:

(a) module docstring 替换为:

```python
"""Replay dumper — used by tools.eval.ckpt --record-replays。`play_and_record`
保留自 dmc_dump_replay.py(签名 / 逻辑不变);新增 `dump_replays_for_ckpt` 包
按 baseline × scenario 批量 dump。"""
```

(b) 删除 `def main():` 函数 + `if __name__ == '__main__': sys.exit(main())` 块 + 不再用的 `import argparse / os / sys` 顶部 import(保留 `import json` / `from pathlib import Path` / `from typing import Optional`)。`play_and_record(...)` 函数(原 line 29-102)签名 / 函数体 全保留。

(c) 文件末尾追加 `dump_replays_for_ckpt`:

```python
def dump_replays_for_ckpt(*, cfg, agent, ckpt_label: str, baselines: list[str],
                          output_dir: Path, save_both_win: bool, only_sid: int,
                          scenarios_seed: Optional[int], paradigm: str):
    """For each baseline × scenario,run case A (agent_side=0) + case B
    (agent_side=1),dump yaml + actions JSON。respect save_both_win + only_sid。"""
    from tools.eval._paradigm import resolve
    from training.dmc.eval.gen_eval_scenarios import generate_eval_scenarios

    build_baseline = resolve(paradigm, 'build_baseline')
    seed = scenarios_seed if scenarios_seed is not None else cfg.eval.scenarios_seed
    scenarios = generate_eval_scenarios(
        seed=seed, n=cfg.eval.n_scenarios,
        team_0=cfg.scenario.team_0, team_1=cfg.scenario.team_1,
        char_pool=cfg.scenario.char_pool, team_size=cfg.scenario.team_size,
        disjoint_teams=cfg.scenario.disjoint_teams,
    )
    for baseline_name in baselines:
        b_dir = output_dir / f'vs_{baseline_name}'
        b_dir.mkdir(parents=True, exist_ok=True)
        for s in scenarios:
            if only_sid >= 0 and s.scenario_id != only_sid:
                continue
            opp_a = build_baseline(baseline_name, seed=s.env_seed, cfg=cfg)
            out_a, yaml_a, act_a = play_and_record(
                cfg, s, agent, opp_a, agent_side=0, max_steps=cfg.max_game_steps)
            opp_b = build_baseline(baseline_name, seed=s.env_seed + 1, cfg=cfg)
            out_b, yaml_b, act_b = play_and_record(
                cfg, s, agent, opp_b, agent_side=1, max_steps=cfg.max_game_steps)
            both_win = out_a > 0 and out_b > 0
            if save_both_win and not both_win:
                continue
            for tag, yaml_str, act_list in (('caseA', yaml_a, act_a), ('caseB', yaml_b, act_b)):
                (b_dir / f'sid{s.scenario_id}_{tag}.yaml').write_text(yaml_str)
                (b_dir / f'sid{s.scenario_id}_{tag}_actions.json').write_text(
                    json.dumps(act_list, indent=2))
            print(f'  {ckpt_label} vs {baseline_name} sid={s.scenario_id} '
                  f'A={out_a:+d} B={out_b:+d}{" ✓both" if both_win else ""}')
```

- [ ] **Step 4: Smoke — 单 ckpt 评 1 baseline**

Run:
```bash
.venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_smoke.toml \
    --ckpts artifacts/<SMOKE_RUN>/latest.pt --baselines random \
    --n-scenarios 4 --output-dir /tmp/eval_smoke/
```
Expected: 打印 wp/ci95 行,生成 `/tmp/eval_smoke/summary.json`,exit 0。

- [ ] **Step 5: Smoke — replay record(--only-sid 0)**

Run:
```bash
.venv/bin/python -m tools.eval.ckpt configs/dmc_stage3_smoke.toml \
    --ckpts artifacts/<RUN>/latest.pt --baselines F1-D2 \
    --record-replays --only-sid 0 --output-dir /tmp/eval_smoke/
ls /tmp/eval_smoke/*/vs_F1-D2/
```
Expected: `sid0_caseA.yaml`, `sid0_caseB.yaml`, `sid0_caseA_actions.json`, `sid0_caseB_actions.json`。

- [ ] **Step 6: Commit**

```bash
git add tools/eval/ckpt.py tools/eval/_replay_runner.py
git commit -m "tools/eval: ckpt.py 合并 dmc_eval_ckpt + dmc_dump_replay (--record-replays / --save-both-win / paradigm registry)"
```

---

## Task 10: rename `dmc_eval_daemon.py` → `tools/eval/daemon.py` + `--paradigm`

**Files:**
- Move: `tools/dmc_eval_daemon.py` → `tools/eval/daemon.py`
- Modify: 新 `daemon.py` 走 paradigm registry

- [ ] **Step 1: git mv**

```bash
git mv tools/dmc_eval_daemon.py tools/eval/daemon.py
```

- [ ] **Step 2: 改 daemon 内部走 paradigm registry**

替换 `_build_eval_agent_from_ckpt` 函数体(原 line 82-94):

```python
def _build_eval_agent_from_ckpt(cfg, ckpt_path: Path, paradigm: str = 'dmc'):
    from tools.eval._paradigm import resolve
    return resolve(paradigm, 'build_agent')(cfg, ckpt_path)


def _ckpt_frame(ckpt_path: Path, paradigm: str = 'dmc'):
    from tools.eval._paradigm import resolve
    return resolve(paradigm, 'ckpt_frame')(ckpt_path)
```

argparse 加:

```python
p.add_argument('--paradigm', default='dmc')
```

evaluator 构造(原 line 158-160)替换:

```python
from tools.eval._paradigm import resolve
load_config = resolve(args.paradigm, 'load_config')
build_evaluator = resolve(args.paradigm, 'build_evaluator')
cfg = load_config(args.config, data_dir=args.data_dir)
evaluator = build_evaluator(cfg)
```

`_run_one_eval` 调用 `_build_eval_agent_from_ckpt(cfg, ckpt_path)` 时,把当前的内部调用都改成接收 `args.paradigm`(或在外层 wrap)。最简单:在 main() 内传 paradigm:

```python
agent = _build_eval_agent_from_ckpt(cfg, ckpt_path, args.paradigm)
```

(更新所有 caller 行)

- [ ] **Step 3: Smoke — 1 iter dry**

Run:
```bash
.venv/bin/python -m tools.eval.daemon configs/dmc_stage3_smoke.toml \
    --run-label dmc_stage3_smoke \
    --remote dev@192.0.2.10:D:/gicg_dev/artifacts \
    --poll-seconds 5 --max-iterations 1
```
Expected: 1 iter rsync + 1 eval(若 Windows 上无 latest.pt 则打印 `no latest.pt yet` 后 exit);关键 import 不挂 + paradigm dispatch 走通。

- [ ] **Step 4: Commit**

```bash
git add tools/eval/daemon.py
git commit -m "tools/eval: rename dmc_eval_daemon → eval/daemon + --paradigm dispatch"
```
