# Phase B · `training/dmc/` 重构 + NaN guard(Task 5-7)

> 父索引:`README.md`。本文件 Task 5 → 6(TDD failing test)→ 7(实现)。

---

## Task 5: `training/dmc/` rename + 合并 single/mp entry

**Files:**
- Rename: `training/dmc/_mp_actor.py` → `training/dmc/_actor.py`
- Rename: `training/dmc/_mp_learner.py` → `training/dmc/_learner.py`
- Rename: `training/dmc/mp_loop.py` → `training/dmc/train.py`(`run_mp_train` → `run`)
- Delete: `training/dmc/train_loop.py`
- Delete: `tools/dmc_train_mp.py`
- Delete: `configs/dmc_mp_smoke.toml`
- Modify: `tools/dmc_train.py`
- Modify: `configs/dmc_stage3_smoke.toml`(加 `num_actors = 1`)

- [ ] **Step 1: git mv 三文件**

```bash
git mv training/dmc/_mp_actor.py training/dmc/_actor.py
git mv training/dmc/_mp_learner.py training/dmc/_learner.py
git mv training/dmc/mp_loop.py training/dmc/train.py
```

- [ ] **Step 2: 修 `training/dmc/train.py` 的 import + 函数名**

Edit:
- `from training.dmc._mp_actor import actor_main` → `from training.dmc._actor import actor_main`
- `from training.dmc._mp_learner import run_learner_loop` → `from training.dmc._learner import run_learner_loop`
- `def run_mp_train(cfg: DmcConfig) -> dict:` → `def run(cfg: DmcConfig) -> dict:`
- 打印行 `[mp] spawning` `[mp] all` `[mp] terminating` `[mp] all actors joined` `[done-mp]` → 改 `[dmc]` `[done]`(对齐合并后的统一语义)
- module docstring 第一行加注:"Single-actor smoke = `cfg.num_actors=1`,full pilot = `cfg.num_actors=24`."

- [ ] **Step 3: 修 `_actor.py / _learner.py` 注释提及**

- `_actor.py` docstring "Spawned by mp_loop driver" → "Spawned by training.dmc.train driver"
- `_learner.py` docstring "Pairs with _mp_actor.py" → "Pairs with _actor.py"

- [ ] **Step 4: 改 `tools/dmc_train.py:29-34` 调 `training.dmc.train.run`**

Replace:

```python
    from training.dmc.config_loader import load_config
    from training.dmc.train import run

    cfg = load_config(args.config, data_dir=args.data_dir)
    summary = run(cfg)
    print(f'[dmc_train] summary: {summary}')
    return 0
```

- [ ] **Step 5: 删 3 个文件**

```bash
git rm training/dmc/train_loop.py tools/dmc_train_mp.py configs/dmc_mp_smoke.toml
```

- [ ] **Step 6: smoke cfg 加 `num_actors = 1`**

Edit `configs/dmc_stage3_smoke.toml`,在 `run_label = "dmc_stage3_smoke"` 之后增一行:

```toml
num_actors = 1                  # Phase 3.5 unified entry: single-actor smoke
```

- [ ] **Step 7: 跑 Mac smoke 验证统一 entry**

Run: `.venv/bin/python -m tools.dmc_train configs/dmc_stage3_smoke.toml`
Expected: 完整跑通(`total_frames=5000`,< 10 min Mac CPU),打印 `[done] summary: ...`,`artifacts/<ts>_dmc_stage3_smoke/{metrics.jsonl, final.pt, summary.json}` 齐全。

- [ ] **Step 8: 全 dmc pytest(确认 rename 不破其他 import)**

Run: `.venv/bin/python -m pytest -n 4 training/tests/test_dmc_*.py -q`
Expected: 全 pass。

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "training/dmc + tools: 合并 single/mp entry → train.run(cfg), 删 train_loop / dmc_train_mp / dmc_mp_smoke.toml"
```

---

## Task 6: TDD — `test_dmc_nan_guard.py`(先写失败测试)

**Files:**
- Create: `training/tests/test_dmc_nan_guard.py`

- [ ] **Step 1: 写测试**

```python
"""Contract test: NaN/inf in train_steps → dump evidence + RuntimeError."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from training.dmc._train_helpers import TrainState, train_steps
from training.dmc.agent import DmcAgent
from training.dmc.config import smoke_config
from training.dmc.replay import DmcReplayBuffer


def _seed_buffer_with_nan(buffer, n: int):
    """Push N transitions whose G=NaN — collated returns 全 NaN → loss=NaN。"""
    from training.dmc._episode import DmcTransition
    for _ in range(n):
        obs_dict = {'dummy_key': torch.zeros(1)}
        t = DmcTransition(obs_dict=obs_dict, action_idx=0, G=float('nan'), n_legal=2)
        buffer.push_episode([t], G=float('nan'))


def test_train_steps_raises_and_dumps_on_nan(tmp_path: Path):
    cfg = smoke_config()
    cfg.batch_size = 2
    agent = DmcAgent(cfg.agent, device='cpu', lr=cfg.learning_rate, epsilon=0.0)
    buffer = DmcReplayBuffer(capacity=64, seed=0)
    _seed_buffer_with_nan(buffer, n=8)
    state = TrainState()

    with pytest.raises(RuntimeError, match='non-finite'):
        train_steps(
            cfg, agent, buffer, tb_writer=None, state=state,
            n_steps_this_ep=1, log_fn=lambda *a, **k: None,
            artifacts_dir=tmp_path,
        )

    dump_dir = tmp_path / f'nan_dump_{state.train_steps}'
    assert dump_dir.exists()
    assert (dump_dir / 'batch.pkl').exists()
    assert (dump_dir / 'pre_step.pt').exists()
    diag = json.loads((dump_dir / 'diag.json').read_text())
    assert diag['train_step'] == state.train_steps
    assert diag['returns_stats']['n_nan'] > 0
```

> **注:** `DmcTransition` 实际字段以 `training/dmc/_episode.py` 当前定义为准。若 `play_one_episode` 的 transition 含额外必填字段(如 `obs_dict` 内具体 keys),mock 数据要按当前结构填(读 `_episode.py:1-130` 确认 dataclass)。如果 mock 复杂度高,改用 `play_one_episode` 跑一局后手改 `transitions[-1].G = float('nan')` 重塞回 buffer。

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest training/tests/test_dmc_nan_guard.py -v`
Expected: FAIL,原因 `train_steps()` 不接受 `artifacts_dir=`(尚未加 kwarg)。

- [ ] **Step 3: Commit 失败测试**

```bash
git add training/tests/test_dmc_nan_guard.py
git commit -m "training/tests: add test_dmc_nan_guard (failing — drives NaN guard implementation)"
```

---

## Task 7: NaN guard 实现 — `_train_helpers.py train_steps` + `_dump_nan_evidence`

**Files:**
- Modify: `training/dmc/_train_helpers.py:95-122`(`train_steps`)
- Append: `training/dmc/_train_helpers.py` 末尾加 `_dump_nan_evidence`
- Modify: `training/dmc/_learner.py:144`(透传 `artifacts_dir`)

> **核心代码已在 design doc 中:** `docs/5_history/dmc_phase35_infra.md:155-184` (新 `train_steps`) 与 `:189-232` (`_dump_nan_evidence`)。Task 7 = 把这两段直接覆盖到对应位置。(归档,implementation done 2026-05-15)

- [ ] **Step 1: 替换 `_train_helpers.py:95-122` `train_steps`**

把 design doc `dmc_phase35_infra.md:155-184` 的 `train_steps` 代码 完整覆盖现有函数体。关键差异:

1. 签名加 `artifacts_dir: Optional[Path] = None`
2. `loss.backward()` 之后、`agent.optimizer.step()` 之前插入 finite 检测
3. 不 finite → 调 `_dump_nan_evidence(...)` → `raise RuntimeError(...)`

注意:design doc 的代码片段缺 `torch.is_tensor(grad_norm)` 兼容判断。`clip_grad_norm_` 返回 tensor(>=1.7),`.isfinite().all()` 直接可用。补全实际代码:

```python
loss_finite = bool(torch.isfinite(loss).all())
gn_finite = bool(torch.isfinite(grad_norm).all()) if torch.is_tensor(grad_norm) \
    else (grad_norm == grad_norm and grad_norm != float('inf'))
if not loss_finite or not gn_finite:
    _dump_nan_evidence(state, agent, batch_transitions, batch_dict, action_idx,
                       returns, logits, loss, grad_norm, artifacts_dir)
    raise RuntimeError(
        f'training step {state.train_steps} produced non-finite '
        f'loss={float(loss.item())} / grad_norm={float(grad_norm)}. '
        f'Evidence dumped to {artifacts_dir}/nan_dump_{state.train_steps}/'
    )
```

- [ ] **Step 2: 在 `_train_helpers.py` 末尾追加 `_dump_nan_evidence`**

把 design doc `dmc_phase35_infra.md:189-232` 的 `_dump_nan_evidence` 完整粘贴到 `_train_helpers.py` 文件末尾。需要额外导入(放文件顶部 import 区):

```python
import pickle  # 已有 json;pickle 是 stdlib,加 import 即可
```

注意:`asdict` 已经 import 自 dataclasses(line 10),`torch` 也已 import,`Path` 已 import。

- [ ] **Step 3: `_learner.py:144` 透传 `artifacts_dir`**

Edit `_learner.py` 第 144 行(`train_steps(cfg, agent, buffer, tb_writer, state, n_train, log)`):

```python
train_steps(cfg, agent, buffer, tb_writer, state, n_train, log,
            artifacts_dir=artifacts_dir)
```

- [ ] **Step 4: 跑 NaN guard 测试**

Run: `.venv/bin/python -m pytest training/tests/test_dmc_nan_guard.py -v`
Expected: PASS。

- [ ] **Step 5: 全 pytest no regression**

Run: `.venv/bin/python -m pytest -n 4 training/tests/ gicg_env/tests/ -q`
Expected: 全 pass。

- [ ] **Step 6: Mac smoke 验证 NaN guard 不影响正常路径**

Run: `.venv/bin/python -m tools.dmc_train configs/dmc_stage3_smoke.toml`
Expected: 跑完 `total_frames=5000`,无 `nan_dump_*` 目录产生(即正常路径未误触发);打印 `[done] summary: ...`。

- [ ] **Step 7: Commit**

```bash
git add training/dmc/_train_helpers.py training/dmc/_learner.py
git commit -m "training/dmc: NaN/inf fail-fast guard — dump batch+ckpt+diag, raise RuntimeError"
```
