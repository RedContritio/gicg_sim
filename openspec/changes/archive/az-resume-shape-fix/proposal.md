---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: az-resume-shape-fix
---

# Proposal — az-resume-shape-fix

## 1. Why

`az-pool-spec-type-fix`(archived 2026-05-17)解锁 AZ smoke_full train-phase
后,A1.6.3 resume-phase 立即触发第三个 pre-existing bug:

```
RuntimeError: output with shape [1, 64] doesn't match the broadcast
shape [1832, 64]
  at torch/optim/adam.py:547 _single_tensor_adam
  param.addcdiv_(exp_avg, denom, value=-step_size)
```

Diagnose(本 change Phase 1):

- Train-phase 末尾 `CheckpointManager.save` 保存 `optimizer.state_dict()`
  (positional `param_groups[].params` → state mapping by index)
- Resume-phase `try_resume` `optimizer.load_state_dict(ckpt['optimizer'])`
  按 **positional order** 把 saved state 装回 new optimizer 的 params
- Post-load 跑 `optimizer.step()` → `exp_avg.shape` 与 `param.shape` 不
  匹配 → broadcast fail

**Root cause**(实测验证):`training/core/network/actor_critic.py:258`
`make_actor_critic`:

```python
for kind in head_kinds:           # head_kinds = AZ_HEAD_KINDS = frozenset({'policy','value','delta'})
    heads[kind] = ...
```

`head_kinds` 是 `frozenset`,Python 3 默认 `PYTHONHASHSEED=random`,**每个
fresh subprocess 的 frozenset 迭代顺序不同**(实测 5 次子进程 4 distinct
orders:`[value,policy,delta]` / `[policy,delta,value]` / `[policy,value,
delta]` / `[value,policy,delta]` / `[value,delta,policy]`)。

→ `nn.ModuleDict heads` 插入顺序变化 → `model.parameters()` 顺序变化 →
`optimizer.param_groups[0]['params']` 顺序变化 → optimizer state 跨 save
/ resume 错位:

- Save subprocess A:`params[119] = value.head.3.weight (1,64)`,
  `params[123] = delta.head.3.weight (1832,64)`
- Resume subprocess B:`params[119] = delta.head.3.weight (1832,64)`,
  `params[123] = value.head.3.weight (1,64)` — **位置颠倒**
- `optimizer.load_state_dict` 按 index 装 state → param[119] (now 1832×64)
  matched with state[119] (saved 1×64) → broadcast fail

**为什么 DMC PASS**:DMC head_kinds = `frozenset({'q'})`,单 head,无顺序
歧义。**AZ / BC / CFR / PPO 都受此 bug 影响**(多 head paradigm),只是
AZ smoke_full 因 az-pool-spec-type-fix unblock 后先 surface,其余 paradigm
smoke_full 仍 skip 着另外的 pre-existing bug。

## 2. What

**Fix**(1 LOC core + invariant ADD):

`training/core/network/actor_critic.py:258` `make_actor_critic`:

```python
# Before
for kind in head_kinds:
# After
for kind in sorted(head_kinds, key=lambda k: list(HEAD_REGISTRY.keys()).index(k)):
```

即:按 `HEAD_REGISTRY` 的 insertion order 排序 `head_kinds` 后再迭代,
确保 `nn.ModuleDict heads` 跨 subprocess deterministic。`HEAD_REGISTRY` 是
module-level dict(line 55),`policy / value / q / avg_policy / delta`
五个固定顺序;Python ≥ 3.7 dict 保插入顺序,跨进程稳定。

为什么不用 `sorted(head_kinds)`(alphabetical):alphabetical 也 deterministic
但语义 implicit;canonical 顺序应取自 registry(显式 single source of truth),
未来 registry 加 head 不需要管 alpha 顺序是否破现有 ckpt。

**Test status update**:

- `training/tests/test_az_smoke_full.py`:remove `@pytest.mark.skip` — 本
  change ship 后 train + resume 全 PASS
- 加 **guard test** `training/tests/test_head_order_deterministic.py`:
  subprocess 跑 ≥ 3 次 `make_actor_critic(cfg, AZ_HEAD_KINDS)`,assert
  `list(model.heads.keys())` 跨 subprocess identical(直接 stress-test
  deterministic ordering invariant)

**Spec delta**:

- `openspec/specs/network-architecture/spec.md` SHALL 12(Generic ActorCritic
  composition)新增 sub-invariant **A12.1**:
  > `make_actor_critic` SHALL iterate `head_kinds` in **`HEAD_REGISTRY`
  > insertion order**,SHALL NOT iterate `head_kinds` directly when its
  > type is `set` / `frozenset`(non-deterministic across processes due
  > to `PYTHONHASHSEED=random`)。
  >
  > Rationale:`heads` 顺序决定 `nn.ModuleDict` insertion 顺序 → 决定
  > `model.parameters()` 顺序 → 决定 `optimizer.state_dict()` 的 positional
  > state mapping。跨 subprocess 不一致 → ckpt save / resume optimizer
  > state 错位 broadcast fail。

## 3. Affected specs

- `network-architecture/spec.md` MODIFY SHALL 12(add sub-invariant A12.1
  on deterministic head ordering)

## 4. Out of scope

- **不动 `CheckpointManager` ckpt schema** — 不引入 per-name optimizer
  state mapping(scope larger than the bug warrants;v2 schema 已 ship)
- **不改 BC / CFR / PPO smoke_full skip 状态** — 它们各自因独立 pre-existing
  bug skip(per memory `project_smoke_full_discovered_bugs_2026_05_17`),
  独立 follow-up
- **不删旧 frozenset 用法** — 5 paradigm 各自的 `XX_HEAD_KINDS = frozenset(...)`
  module-level 常量保留(frozenset 表 closed set 语义);fix 仅在
  iteration 处 enforce deterministic order
- **不补救已 saved 的 broken ckpt** — AZ resume 之前是完全 broken 的(此 bug
  存在期间任何 ckpt resume 都失败),无 in-the-wild 受影响 ckpt 可救
