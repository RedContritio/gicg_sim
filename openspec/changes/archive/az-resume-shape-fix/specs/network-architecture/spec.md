---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: network-architecture
---

# Spec delta — network-architecture(A12 deterministic head ordering)

post `az-pool-spec-type-fix` archive 解锁 AZ smoke_full train-phase 后,
A1.6.3 resume-phase 触发 `optimizer.step()` `RuntimeError: output with
shape [1, 64] doesn't match the broadcast shape [1832, 64]`。

诊断证实 root cause:`training/core/network/actor_critic.py:258`
`make_actor_critic` 迭代 `head_kinds`(typed `set[str]` / `frozenset[str]`)
顺序跨 subprocess 不一致(`PYTHONHASHSEED=random`),→ `nn.ModuleDict heads`
插入顺序变化 → `model.parameters()` 顺序变化 → `optimizer.state_dict()` 的
positional state mapping 跨 save / resume 错位 → broadcast fail at first
post-resume `optimizer.step()`。

实测 5 fresh subprocess `list(AZ_HEAD_KINDS)` 得 4 distinct orders。

本 delta 在 SHALL 12(Generic ActorCritic composition)新增 sub-invariant
A12.1 治理 head iteration 顺序 determinism。

## MODIFY

### M-A12-1: Deterministic head iteration order

加入 network-architecture/spec.md §3 SHALL 12 末尾,作为 sub-invariant
**A12.1**:

```markdown
**A12.1**(deterministic head ordering pre-condition):`make_actor_critic`
(`training/core/network/actor_critic.py`)SHALL iterate `head_kinds` in
**`HEAD_REGISTRY` insertion order**(module-level dict at line 55:
`{'policy', 'value', 'q', 'avg_policy', 'delta'}` — Python ≥ 3.7 dict 保
插入顺序 stable across processes)。SHALL NOT 直接 `for kind in head_kinds:`
迭代 — `head_kinds` typed as `set[str]` / `frozenset[str]`,默认
`PYTHONHASHSEED=random` 下 iteration order 跨 subprocess 不同,导致
`nn.ModuleDict heads` 插入顺序、`model.parameters()` 顺序、
`optimizer.state_dict()` positional state mapping 跨 save / resume 错位
→ `optimizer.step()` post-resume `addcdiv_` 因 `exp_avg.shape` 与
`param.shape` 不一致 raise `RuntimeError: output with shape [...] doesn't
match the broadcast shape [...]`。

Canonical iteration form:

    _REGISTRY_ORDER = {k: i for i, k in enumerate(HEAD_REGISTRY)}
    for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):
        heads[kind] = ...

Rationale(why registry order,not alphabetical):`HEAD_REGISTRY` is the
single source of truth for known head kinds(invariant 12);ordering by
registry 保 future 加 head 时 ckpt schema 仍 stable(不被 alphabetical
ordering 偶然推翻)。

Guard test(`training/tests/test_head_order_deterministic.py`)
subprocess-stress assert `list(make_actor_critic(cfg, kinds).heads.keys())`
跨 ≥ 3 fresh subprocess identical for AZ / BC / PPO head sets。
```

## Status Revised entry

`network-architecture/spec.md` §6 Status 加:

```markdown
- **Revised**:2026-05-17(`az-resume-shape-fix` archive)— +A12.1
  sub-invariant(deterministic head iteration order in `make_actor_critic`,
  治理 frozenset `head_kinds` iteration 跨 subprocess 不一致 → ckpt save
  / resume optimizer state 错位 broadcast fail)。修复 AZ smoke_full
  A1.6.3 resume-phase 阻塞,unskip `test_az_smoke_full.py`。
```
