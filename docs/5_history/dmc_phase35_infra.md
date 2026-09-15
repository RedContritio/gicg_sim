> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **IMPLEMENTED 2026-05-15**
> - 实施 commit 链(2026-05-15 13:11-14:20):c67b9ba(remote/_common)→ 2da97a0(remote/run)→ a4e7181(PS-safe)→ 18206bb(win_status rename)→ c675f34(remote/sync)→ ce5049e(dmc 合并 single/mp entry)→ 4c43b92(nan_guard test failing-first)→ 3f3510c / 5ae3f7c(NaN guard impl)→ 2449ce6 / bb51d4d / 2278558(tools/eval paradigm registry)→ d818ff3(metrics_view + compare)→ 29b3966(remote/pull + build_engine)
> - 全部 12 task ✓
> - tools/eval/ + tools/remote/ + training/dmc/ refactor done

---

# DMC Phase 3.5 基础设施重构 + NaN root-cause 修复

> 2026-05-15 落盘。
>
> 上下文:Stage 3 1-char pilot 完成(peak vs F1-D2 = 0.70,4 baseline 全过 0.5)
> 后,识别出 reusable infra(SSH 链 / paradigm-agnostic eval / metrics 解析)
> 与 1 个待彻查 numerical bug(loss=NaN 后 weights → NaN → argmax 永远 0)。

## A · tools/ 重构(paradigm-agnostic 子目录)

### A.1 `tools/remote/` — Windows GPU box 通用 infra

不与训练 paradigm 耦合(PPO/AZ/CFR/DMC 都可用)。

```
tools/remote/
├── _common.py       # REMOTE='dev@192.0.2.10', REMOTE_ROOT=r'D:\gicg_dev',
│                    # ssh_run(ps_script, timeout) / scp_to(local, remote) /
│                    # scp_from(remote, local). 处理 utf8/env/cp936 stderr。
├── sync.py          # Mac → Windows. 模式:--single <file> / --tar-all / --git-changed
├── run.py           # 跑任意 python module on Windows
│                    #   `python -m tools.remote.run python -m tools.dmc_train cfg.toml`
│                    # 自动设 OMP_NUM_THREADS=1 / PYTHONIOENCODING=utf-8 / PYTHONUNBUFFERED=1
├── pull.py          # Windows → Mac.  `python -m tools.remote.pull <run_label>`
│                    # 拉 artifacts/<run>/metrics.jsonl + summary.json + latest.pt
├── build_engine.py  # cgo build libgicg.dll on Windows(设 CGO_ENABLED+CC+PATH)
├── status.py        # ← rename 自 dmc_win_status.py.  GPU/CPU/MEM + metrics tail
└── status.ps1       # ← rename 自 dmc_status.ps1.    Windows side script
```

### A.2 `tools/eval/` — paradigm-agnostic eval/replay

```
tools/eval/
├── _paradigm.py     # PARADIGMS = {'dmc': {'load_config':..., 'agent_class':...,
│                    #                       'evaluator_class':..., 'baseline_builder':...},
│                    #               'az': {...}, 'cfr': {...}}.  resolve(p, key) dynamic import
├── ckpt.py          # 合并 dmc_eval_ckpt.py + dmc_dump_replay.py.
│                    # `--ckpts a.pt b.pt ...` 多 ckpt 同 scenarios_seed → deterministic 对比
│                    # `--baselines random F1-D2 F1-D4 dmc:hist.pt`
│                    # `--n-scenarios N`
│                    # `--record-replays` 所有 scenarios dump yaml + actions json
│                    # `--save-both-win` 只 dump 同 scenario swap_sides 双赢的
│                    # 输出 <output-dir>/<ckpt_label>/vs_<baseline>/sid<N>_caseA.yaml
│                    # user 用 `diff` / 任意 yaml diff 看 ckpt 间策略差异
├── daemon.py        # rename 自 dmc_eval_daemon.py + --paradigm
├── metrics_view.py  # 新.  解析 artifacts/<run>/metrics.jsonl,显示
│                    #   - last eval row (per baseline wp + CI95)
│                    #   - fps window(early vs late)
│                    #   - loss / grad_norm 走势 + NaN/inf detection
│                    #   - 推算训练 ETA based on cfg.total_frames
└── compare.py       # 新.  多 eval JSON 输出对比 markdown 表
                     #   `python -m tools.eval.compare a.json b.json c.json`
                     #   表头各 baseline,行各 ckpt,值 wp ± CI95 半宽
```

`replay diff` 不单独 — 用 `eval/ckpt.py --ckpts a b --record-replays`,同 scenarios_seed
deterministic,两边输出 yaml 在 `<out>/a/`vs`<out>/b/`,用户用 `diff` 直接对比。

### A.3 paradigm-specific training entry

```
tools/dmc_train.py    # 唯一 entry,极简
                      #   load cfg → call training.dmc.train.run(cfg)
                      # 没有 single/mp 区分,smoke/pilot/stage3 完全通过 cfg.toml 区分
                      #   - num_actors=1 + total_frames=2000 = smoke
                      #   - num_actors=24 + total_frames=100M = stage3
                      #   - device=cpu / cuda 通过 cfg
```

### A.4 删除

- `tools/dmc_train_mp.py` — 合入 `tools/dmc_train.py`
- `tools/dmc_eval_ckpt.py` → `tools/eval/ckpt.py`
- `tools/dmc_dump_replay.py` → `tools/eval/ckpt.py --record-replays`
- `tools/dmc_eval_daemon.py` → `tools/eval/daemon.py`
- `tools/dmc_win_status.py` → `tools/remote/status.py`
- `tools/dmc_status.ps1` → `tools/remote/status.ps1`

## B · `training/dmc/` 重构

```
training/dmc/
├── train.py             # 整合自 mp_loop.py.  唯一 driver:run(cfg) → spawn N actor + learner
├── _actor.py            # rename 自 _mp_actor.py
├── _learner.py          # rename 自 _mp_learner.py + NaN root-cause 检测 + fail-fast
├── _episode.py          # 不变 (actor + eval 共用)
├── _train_helpers.py    # 不变 (learner 用 setup/resume/save/train_steps/finalize)
├── _resume_helpers.py   # 不变
├── agent.py / config.py / loss.py / opponent_pool.py / replay.py / config_loader.py
└── eval/
```

### 删除

- `training/dmc/train_loop.py`(整个文件 — `run_smoke` 不存在,mp 路径覆盖所有场景)
- `training/dmc/mp_loop.py` → rename → `training/dmc/train.py`
- `training/dmc/_mp_actor.py` → `_actor.py`
- `training/dmc/_mp_learner.py` → `_learner.py`

### cfg 调整

`configs/dmc_stage3_smoke.toml`:
- 加 `num_actors = 1`(Mac CPU 单 actor 测 pipeline)
- 删 `num_actors=4` 的独立 `dmc_mp_smoke.toml`(合并)

`configs/dmc_stage3_pilot.toml`:
- 保持 `num_actors = 24`(Windows GPU)

## C · NaN root-cause 修复(NOT skip,fail-fast + 留证据)

### 背景

Stage 3 fixed engine pilot (frames=20011,1215 ep):
- 训练后期 train: step=4550 loss=NaN
- net weights → inf/NaN → argmax 永远返 index 0 → policy 退化到"出第一张牌"
- final ckpt vs F1-D2 = 0.066(原本 peak 0.625)

### 处理原则

**不 patch skip NaN batch**(那是掩盖问题)。**Fail-fast + 留证据彻查 root cause**:

1. `training/dmc/_learner.py` train step loop 后加 `_check_finite_or_raise(loss, grad_norm, agent, ...)`
2. 检测到 NaN/inf 时:
   - 创建 `artifacts/<run>/nan_dump_<train_step>/` 目录
   - dump `batch.pkl`:本 step 的 batch_transitions(transitions list pickle 化)+ collated batch dict + action_idx + returns
   - dump `pre_step.pt`:上一步成功的 net + optimizer state(NaN 前的最后干净 checkpoint)
   - dump `diag.json`:
     ```json
     {
       "train_step": 4550,
       "frame": 18234,
       "loss": "NaN",
       "grad_norm_pre_clip": 1e9,
       "batch_G_stats": {"min": -1, "max": 1, "n_zero": 0, "n_nan": 0},
       "selected_logits": {"min": ..., "max": ..., "n_nan": ...},
       "batch_obs_keys_any_nan": [...]
     }
     ```
   - **raise RuntimeError → 训练立即终止**
3. 人工分析(reproduce):
   - Load `pre_step.pt` → 用 `batch.pkl` 跑 single forward+backward → 复现 NaN
   - 定位:
     - 是 input obs 含 NaN? (encode 上游 bug)
     - 是 G 异常? (truncated episode + max_rounds 边界)
     - 是 grad explode 由某 action_idx 边界 case?
     - 是 specific transition 的 hook_types/values 包含异常?
   - 修 root cause(可能在 engine 输出 / step_encoding / loss 计算某一处)
4. **NOT 加 try/except skip,NOT 调 grad_norm 阈值**(那只是延后症状)

### 实现位置

`training/dmc/_train_helpers.py` `train_steps()` 加:

```python
def train_steps(cfg, agent, buffer, tb_writer, state, n_steps_this_ep, log_fn,
                artifacts_dir=None):
    for _ in range(n_steps_this_ep):
        if len(buffer) < cfg.batch_size:
            break
        batch_transitions = buffer.sample(cfg.batch_size)
        batch_dict, action_idx, returns = collate_batch(...)
        logits, _value, _delta = agent.forward_batch(batch_dict)
        loss = dmc_mse_loss(logits, action_idx, returns)
        agent.optimizer.zero_grad()
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(agent.net.parameters(), cfg.max_grad_norm)

        # NaN/inf detection — fail-fast + 留证据
        if not torch.isfinite(loss).all() or not torch.isfinite(grad_norm).all():
            _dump_nan_evidence(
                state, agent, batch_transitions, batch_dict, action_idx,
                returns, logits, loss, grad_norm, artifacts_dir,
            )
            raise RuntimeError(
                f'training step {state.train_steps} produced non-finite '
                f'loss={loss.item()} / grad_norm={float(grad_norm)}. '
                f'Evidence dumped to {artifacts_dir}/nan_dump_{state.train_steps}/'
            )

        agent.optimizer.step()
        state.train_steps += 1
        # ... log / tb
```

`_dump_nan_evidence()` 实现写到同文件:

```python
def _dump_nan_evidence(state, agent, batch_transitions, batch_dict, action_idx,
                      returns, logits, loss, grad_norm, artifacts_dir):
    import pickle, json
    if artifacts_dir is None:
        artifacts_dir = Path('.')
    dump_dir = artifacts_dir / f'nan_dump_{state.train_steps}'
    dump_dir.mkdir(parents=True, exist_ok=True)

    # batch.pkl: 原始 transitions + collated dict
    with open(dump_dir / 'batch.pkl', 'wb') as f:
        pickle.dump({
            'transitions': batch_transitions,
            'batch_dict': {k: v.cpu().numpy() if torch.is_tensor(v) else v
                           for k, v in batch_dict.items()},
            'action_idx': action_idx.cpu().numpy(),
            'returns': returns.cpu().numpy(),
        }, f)

    # pre_step.pt: 当前 (即将爆) ckpt — 含 NaN 之前最后干净 state
    torch.save({
        'net': agent.net.state_dict(),
        'optimizer': agent.optimizer.state_dict(),
        'state': asdict(state),
    }, dump_dir / 'pre_step.pt')

    # diag.json: 数值摘要
    diag = {
        'train_step': state.train_steps,
        'frame': state.frames,
        'loss': float(loss.item()) if torch.is_tensor(loss) else loss,
        'grad_norm': float(grad_norm) if torch.is_tensor(grad_norm) else grad_norm,
        'returns_stats': {
            'min': float(returns.min()), 'max': float(returns.max()),
            'n_nan': int(returns.isnan().sum()), 'n_inf': int(returns.isinf().sum()),
        },
        'logits_stats': {
            'min': float(logits.min()), 'max': float(logits.max()),
            'n_nan': int(logits.isnan().sum()), 'n_inf': int(logits.isinf().sum()),
        },
        'batch_keys_any_nan': [k for k, v in batch_dict.items()
                               if torch.is_tensor(v) and torch.isnan(v).any()],
    }
    (dump_dir / 'diag.json').write_text(json.dumps(diag, indent=2))
```

### 修 root cause 后

加单元测试:`training/tests/test_dmc_nan_guard.py` — 构造 mock batch 触发已知 NaN
path → 验证 dump 内容 + raise 行为。

## D · 优先级 / 实施顺序

1. **`tools/remote/_common.py` + `run.py` + `sync.py`** — 立即解放手动 ssh+powershell+scp 链
2. **`tools/remote/status.py`** 从 dmc_win_status.py 改名(已有内容,只需迁移)
3. **`training/dmc/train.py` + 删 train_loop.py / mp_loop.py / single-process entry** — paradigm 重构
4. **NaN guard fail-fast + evidence dump**(C 节) → **触发 1 次重训 pilot,实际收集 NaN 证据**
5. **`tools/eval/_paradigm.py` + ckpt.py** — eval 统一入口
6. **`tools/eval/metrics_view.py` + compare.py** — 看结果效率
7. **`tools/eval/daemon.py`** — Mac eval daemon 从 dmc_eval_daemon 改名
8. **`tools/remote/pull.py` + build_engine.py** — 一周一次的非高频工具

## E · 验收标准

- `tools/dmc_train.py configs/<smoke|pilot|stage3>.toml` 单 entry 跑 smoke 不崩
- `tools/remote/run.py python -m tools.dmc_train configs/dmc_stage3_pilot.toml`
  替代当前长 ssh+powershell 链
- 跑 pilot 触发 NaN(if 仍存在)→ 终止 + 留 nan_dump_<step>/ 目录 + raise
- `tools/eval/ckpt.py --ckpts a b --record-replays --search-both-win` 替代
  原 dmc_eval_ckpt + dmc_dump_replay 联合调用
- `git diff` 两 ckpt 的 yaml 输出可直接对比策略
- 全 pytest pass(test_dmc_*.py + 新 test_dmc_nan_guard.py)

## F · 不在本次 scope

- Stage 4(multi-char + char_pool 抽样 + 元素反应)— 仅 Stage 3 工具完善
- AZ / CFR paradigm 注册 — paradigm registry 接口预留,实际只填 `'dmc'` entry
- Phase 3.5 Windows 实测 24-actor pilot — 等本次基建完成后再跑(用新 entry)
