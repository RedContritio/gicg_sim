---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfr-driver-buffer-multihead-fix
---

# Proposal — cfr-driver-buffer-multihead-fix

## 1. Why

`paradigm-smoke-full-tier`(archived 2026-05-17)落地后 5 paradigm 之一
CFR `test_cfr_smoke_full.py` 因 pre-existing CFR ↔ generic driver
contract gap 被 `pytest.skip`,SF-105 把修复列为 follow-up:

- `training/core/pipeline.py:93` 调 `buffer.sample(plan.batch_size)`
  (generic single-buffer Buffer protocol);
- `training/paradigms/cfr/paradigm.py:39-90` `_CFRBufferBundle.sample`
  raise `RuntimeError("CFR buffer is 3-headed (advantage[0/1] + strategy);
  driver SHALL call sample_head(...) instead.")` — CFR 维护 3 reservoir
  (advantage[player0/player1] + strategy + value),无法用一次
  single-head sample 调用喂 driver。

CFR 在 `frozen-research` tier(spec paradigm-cfr/spec.md C6.1 + C6.3),
**禁止开启 new production run**,仅保留 r008 reproducibility(C6.2 已
SUPERSEDED 但 tier 仍 freeze)。因此 production 路径完全不动,仅修复
smoke test 端 — 让 smoke_full 跑通 driver 入口 + ckpt save/load/resume
infra,不要求 CFR train quality。

User 显式要求(per SF-105 / D-601 revision):"smoke 测试不要求 CFR
真正训练,只需验证 driver 路径 + ckpt 落盘 + resume 连通"。

## 2. What

**3 bullets**(test-only,production CFR 不动):

1. **新 `_SmokeStubBuffer` class in `training/tests/test_cfr_smoke_full.py`**
   实现 generic `Buffer` protocol(`push` / `sample(batch_size, rng?)` /
   `clear` / `__len__` / `state_dict` / `load_state_dict` / `capacity`),
   `sample` 返回 minimal valid `Batch.data` 含 CFRLoss `REQUIRED_KEYS`
   (`head` + `pred` + `target` + `legal_mask`,leaf tensor with
   requires_grad=True 让 backward 走通 no-op grad path)
2. **Monkeypatch `CFRParadigm.make_buffer` via `--override` 不可行(buffer
   是 paradigm-impl 内部 factory),改在 test 内 `tools.run` 起 subprocess
   之前 inject stub** — 通过环境变量 `GICG_CFR_SMOKE_STUB_BUFFER=1` 或在
   `training.paradigms.cfr.paradigm` 模块 import 时检测 env flag,switch
   make_buffer 到 stub
3. **移除 `test_cfr_smoke_full.py` 的 `@pytest.mark.skip`** + 加 fixture
   set env flag 给 subprocess

## 3. Affected specs

- `paradigm-cfr/spec.md`:ADD invariant C6.4 允许 smoke-only stub buffer
  injection 在 frozen-research tier(明示不打破 tier freeze — stub 仅服务
  test infra,不创造 new training run)
- 主 `training-architecture/spec.md` 无修改(generic Buffer protocol 不动)

## 4. Out of scope

- **不动** production `_CFRBufferBundle`(C3.1 双 reservoir 仍 SHALL
  保留;CFR 真正 unfreeze + 切 single-head 需独立 OpenSpec change)
- **不写** 新 paradigm-local driver(option B in proposal queue,留作未来
  unfreeze 路径)
- **不修复** CFR collector / loss / network — 它们 spec C5 / C2 / C4 不动
- **不要求** smoke_full 验证 CFR train quality — 仅 infra 连通

## 5. Decision summary(详 design.md retrospective)

- **Option C(smoke-only stub buffer)选中**:vs Option A(driver 加
  multi-head buffer protocol;打破 generic 假设)/ Option B(CFR
  paradigm-local driver;~300 LOC)/ Option C 最小侵入,纯 test infra,
  ~50-80 LOC test
- **Stub buffer 在 test file 内,不污染 production**:与
  `bc-smoke-dataset-fixture`(planned follow-up)同 pattern — smoke-only
  fixture 留在 `training/tests/`,production import 路径 0 touch
- **Env-flag dispatch in paradigm.py**:subprocess 隔离要求 stub
  injection 通过 subprocess boundary;monkeypatch 在 parent process 无效
  — env flag 是干净的 cross-process boundary
- **Tier freeze 不破**:per C6.3,frozen-research 禁止 new run;stub
  仅在 `GICG_CFR_SMOKE_STUB_BUFFER=1` 下启用,production driver 始终走
  `_CFRBufferBundle`,tier 状态不变(C6.4 ADD 明示这一点)
