---
last_updated: 2026-05-17
status: ARCHIVED
schema_version: 0
change_id: cfr-driver-buffer-multihead-fix
---

# cfr-driver-buffer-multihead-fix — Design Retrospective

> Archive-time retrospective(≤ 200 lines per archive cap)。

## Verdict

**成功** — Option C(smoke-only stub buffer via env flag)落地。CFR
`test_cfr_smoke_full` 移除 skip,PASS;production CFR(`_CFRBufferBundle`)
未动,frozen-research tier(C6.1 + C6.3)状态不变;新增 C6.4 明示
stub 允许。146 CFR production test 0 regression,1004 整 sweep 0 regression。

## What we built

- `training/tests/_cfr_smoke_stub.py` 新增 108 LOC — `_SmokeStubBuffer`
  实现 generic Buffer protocol(`capacity` / `push` / `sample(batch_size,
  rng?)` / `clear` / `__len__` / `state_dict` / `load_state_dict`);
  `sample` 返回 `Batch.data` 含 CFRLoss `REQUIRED_KEYS`(`head` + `pred` +
  `target` + `legal_mask`),`pred` 是 leaf tensor with `requires_grad=True`
  让 backward 走通(loss=0,grad propagates to leaf only;clip_grad_norm
  对 network params 返回 0 因 grad=None;optimizer.step skip grad=None
  param);head 交替 advantage/strategy 覆盖 CFRLoss 双分支
- `training/paradigms/cfr/paradigm.py` 加 12 LOC env-flag dispatch in
  `make_buffer`:`os.environ.get('GICG_CFR_SMOKE_STUB_BUFFER') == '1'`
  → lazy import `_SmokeStubBuffer` 并返回;否则走 production
  `_CFRBufferBundle`。Lazy import 保证 production import 链 0 触
  `training/tests/*`
- `training/tests/smoke_full_template.py` 加 `extra_env` + `max_steps`
  optional 参数(18 LOC):extra_env 通过 subprocess `env=` 注入 stub
  flag(parent process env 不变);max_steps 透传 `tools.run --max-steps`,
  让 CFR initial run cap 在 step 30(cfg n_iterations=50),resume 跑到
  50 → 产生新 ckpt_40 / ckpt_50 文件(否则 initial 跑到 50 后 ckpts
  全已存在,resume 仅覆盖无新 file)
- `training/tests/test_cfr_smoke_full.py` 移除 `@pytest.mark.skip`,加
  protocol-assert test `test_smoke_stub_buffer_satisfies_protocol`(catch
  Buffer protocol 未来变更)+ smoke_full test 用 `extra_env={'GICG_CFR_SMOKE_STUB_BUFFER':
  '1'}` + `max_steps=30`
- `configs/cfr/smoke_full.toml` bump `n_iterations` 30 → 50 + 加 cfg
  comment 解释 stub 路径 + initial cap 逻辑;`keep_last_n` 5 → 10
- `openspec/specs/paradigm-cfr/spec.md` ADD C6.4 SHALL(明示 stub 允许
  + tier freeze 不破)+ Revised entry + cross-ref;现有 C7.x 编号
  保持(18 → 19,19 → 20,20 → 21 以避免与新 C6.4 冲突)

## Tradeoffs revisited

- **Option C vs A vs B**:预期 SELECTED C ✓ — Option A(driver 加
  multi-head protocol)需 ~150 LOC core 改 + 4 paradigm 适配,打破
  generic 假设;Option B(CFR-local driver)~300 LOC,复制 driver 大半。
  Option C ~50-80 LOC test-only,production 0 触,scope 最小。实际
  ship ~140 LOC(stub 108 + paradigm 12 + template 18 + test 净增 ~25
  + cfg/spec/docs ~50),仍是 3 个 option 里最轻量
- **Stub location 单独文件 vs test 内联**:预期 单独文件 ✓ — `_cfr_smoke_stub.py`
  独立模块,paradigm.py lazy import 仅在 env flag set 时触发,production
  import 链 0 触 `training/tests/*`。test 内联会让 paradigm import
  `from training.tests...` 创造 test-prod 循环引用风险
- **Env flag vs cfg flag**:预期 env flag ✓ — cfg flag 需 cfg dataclass
  加字段 + validator + 全 paradigm cfg 影响。env flag 是 subprocess
  boundary clean 的 dispatch(parent process patch 不传 child),且
  仅 CFR paradigm 用,scope 隔离
- **pred 是 leaf tensor vs 连 network**:预期 leaf ✓ — CFRLoss `del network`
  本来不调网络,pred 连 network 也无意义。leaf tensor with `requires_grad=True`
  让 backward 走通自身,clip_grad_norm 对 network params(grad=None)返回
  0 finite,NaNGuard 通过,optimizer.step 跳过 grad=None param。driver
  路径完整走通,不需任何 hack
- **Resume 新 ckpt 验证 — max_steps cap**:预期未提,实际暴露 ✓ —
  CFR n_iterations 是 hard step cap,resume from earliest ckpt 仍受同
  cap 制约,跑到原 final step 时所有 ckpt 文件已存在,resume 仅覆盖
  无新 file。修法:initial run 用 `--max-steps=30` cap 在中段,resume
  无 cap 跑到 n_iterations=50 → 产生 ckpt_40 / ckpt_50 strict 新文件。
  这是 step-based terminus paradigm 通用 pattern(BC future fixture
  也可能需)

## Surprises

- **`isinstance(stub, Buffer)` runtime_checkable 直接 work**:预期可能
  需 explicit `@runtime_checkable` decorator dance;实际 Python 3.14
  `Protocol` + `runtime_checkable` 已支持 structural check,stub 7
  方法齐全直接 pass。优势:协议未来加方法,protocol-assert test 会
  fail-fast 提示同步 stub
- **libgicg.dylib 未跨 worktree 共享**:预期 worktree symlink 共享,
  实际每 worktree 独立 build。首次 smoke_full 跑挂提示 FileNotFoundError
  + build 命令,build 后秒过。这是 worktree workflow 已知 friction
  (`gicg_env/libgicg.dylib` git-ignored),不是本 change 责任
- **NaNGuard + clip_grad_norm 对 grad=None 全 graceful**:预期可能要
  fake grad inject;实际 `torch.nn.utils.clip_grad_norm_` 对 grad=None
  param 返回 0.0(skip),`AdamW.step` 对 grad=None param 也 skip,
  全 well-defined no-op,stub 路径 0 hack

## Spec delta summary

本 change 修订 **1 个 capability spec**(paradigm-cfr):

- **paradigm-cfr/spec.md**:
  - **ADD A-C6.4**:Test infrastructure SHALL be allowed to inject
    smoke-only stub buffer via `GICG_CFR_SMOKE_STUB_BUFFER=1` env flag,
    仅 for `pytest -m smoke_full`;production runs SHALL NOT set;
    `_CFRBufferBundle` remains the only production buffer;tier freeze
    (C6.1 + C6.3)SHALL NOT be considered violated
  - **MODIFY**:C7.x 编号 18-20 → 19-21(C6.4 占用 18 编号)
  - **Status section**:+Revised entry(2026-05-17 cfr-driver-buffer-multihead-fix
    archive ADD C6.4)
  - **Cross-references**:+archive link `cfr-driver-buffer-multihead-fix`

无其他 capability spec 修订。`training-architecture` 的 generic Buffer
protocol 不变(stub 顺从 protocol,不要求 protocol 改动)。
