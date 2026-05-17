---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfr-driver-buffer-multihead-fix
target_spec: openspec/specs/paradigm-cfr/spec.md
---

# Spec delta — paradigm-cfr

## ADD invariants(C6.x tier section)

### C6.4 Smoke-only stub buffer 允许(本 change ADD)

22. **C6.4** Test infrastructure SHALL be allowed to inject a smoke-only
    stub buffer into `CFRParadigm.make_buffer` via env flag
    `GICG_CFR_SMOKE_STUB_BUFFER=1`,**仅** for `pytest -m smoke_full`
    coverage of the generic driver(`training/core/pipeline.py`)→ CFR
    paradigm wiring。Production runs SHALL NOT set this flag;
    `_CFRBufferBundle`(C3.1 双 reservoir)remains the only production
    buffer。Stub buffer SHALL NOT be used for CFR training quality
    verification — its sole purpose is exercising driver collect →
    sample → loss → backward → optimizer.step → ckpt save/resume infra
    when CFR `_CFRBufferBundle.sample()` raises由 generic single-buffer
    driver contract gap。

    Tier freeze(C6.1 + C6.3)SHALL NOT be considered violated by stub
    buffer activation — smoke test does not launch a "new CFR
    production run",it only validates infra connectivity using a
    minimal valid `Batch` payload(per CFRLoss `REQUIRED_KEYS`)。

## Rationale

`paradigm-smoke-full-tier`(archive 2026-05-17)SF-105 列出 CFR
`test_cfr_smoke_full.py` skip 由 `_CFRBufferBundle.sample` raise
RuntimeError(generic pipeline 调 single-head sample,CFR 维护
advantage[0/1] + strategy + value 3 reservoir)。

Option C(smoke-only stub buffer)被选中作 follow-up 修复路径,vs
A(driver multi-head 协议,~150 LOC core + 4 paradigm 适配,打破
generic 假设)或 B(CFR paradigm-local driver,~300 LOC)— Option C
最小侵入,纯 test infra,production CFR 路径 0 触。

Stub buffer 仅在 env flag 开启时由 `CFRParadigm.make_buffer` dispatch,
production driver 始终走 `_CFRBufferBundle`。C6.4 ADD 明示这是允许的,
不打破 tier freeze 语义(stub 不创造 new training run,仅 smoke 验证
driver wiring)。

## Cross-references

- 触发 change:`paradigm-smoke-full-tier`(archive)
- 主 spec invariants 序号:C6 段(C6.1-C6.3 existing,C6.4 new by this
  change)
- Generic Buffer protocol:`training/core/protocols.py:206-218`
- Sibling pattern(planned):`bc-smoke-dataset-fixture`
