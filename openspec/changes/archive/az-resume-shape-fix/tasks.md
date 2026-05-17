# az-resume-shape-fix — tasks

Single-session follow-up fix(~5 LOC code + guard test + spec delta + AZ
smoke_full unskip)。

## T1 — Fix `make_actor_critic` head ordering

- [x] T1.1 `training/core/network/actor_critic.py` — add module-level
  `_REGISTRY_ORDER = {k: i for i, k in enumerate(HEAD_REGISTRY)}` +
  change `for kind in head_kinds:` →
  `for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):`
  with inline rationale comment(A12.1)。
- [x] T1.2 verify:`make_actor_critic(cfg, AZ_HEAD_KINDS)` 跨 subprocess
  produce identical `list(model.heads.keys())`(T2 guard test PASS)

## T2 — Guard test for deterministic head ordering

- [x] T2.1 NEW `training/tests/test_head_order_deterministic.py`:
  - subprocess-invoke `python -c '...'` 3 次 dump
    `list(make_actor_critic(cfg, AZ_HEAD_KINDS).heads.keys())`
  - assert 3 输出 identical
  - 覆盖 AZ_HEAD_KINDS / BC_HEAD_KINDS / PPO_HEAD_KINDS(3 multi-head paradigm)
  - default unit tier(无 smoke mark)— 3 tests / ~5s wall

## T3 — Unskip AZ smoke_full

- [x] T3.1 `training/tests/test_az_smoke_full.py`:
  - removed `@pytest.mark.skip(reason='az-resume-shape-fix')` decorator
  - 改写 docstring:删 STATUS-FAIL 段(bug 已修),改记 POST archive 状态 +
    prior history pointers
- [x] T3.2 verify:`pytest -m smoke_full training/tests/test_az_smoke_full.py
  -v --tb=long` PASS(train + resume + new ckpts post-resume)
  → 实测 wall = 59.5s,远低于 SF-104 15min cap

## T4 — Spec delta merge

- [x] T4.1 `openspec/changes/az-resume-shape-fix/specs/network-architecture/spec.md`
  写 A12.1 MODIFY delta
- [ ] T4.2 archive 时 merge 入 `openspec/specs/network-architecture/spec.md`
  SHALL 12 后追加 A12.1 sub-invariant;Status section +Revised entry
- [x] T4.3 `tools/_meta/check_openspec_indices` pass

## T5 — Verification

- [x] T5.1 AZ smoke_full PASS:`pytest -m smoke_full
  training/tests/test_az_smoke_full.py -v`
- [x] T5.2 AZ baseline no regression:189/189 PASS via `pytest
  training/tests/test_az_*.py training/tests/test_actor_critic_composition.py
  training/tests/test_head_order_deterministic.py
  training/tests/test_determinize.py`
- [x] T5.3 其它 paradigm smoke_full no regression:BC/CFR/DMC PASS,
  PPO skip unchanged
- [x] T5.4 `tools/_meta/check_line_limits`:本 change touch files all
  within limits(actor_critic.py 297 < 300;test_head_order_deterministic.py
  99 < 500)
- [x] T5.5 Full training tests sweep(known-bad ignored):999 passed /
  3 skipped / 0 failed
