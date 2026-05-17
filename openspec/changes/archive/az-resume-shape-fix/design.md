# az-resume-shape-fix — Design Retrospective

> Archive-time retrospective(≤ 200 lines per archive-workflow.md SOP)。
> 极轻量 follow-up(2 LOC code + 99 LOC guard test + spec sub-invariant)。

## Verdict

**完全成功** — 实测 4 distinct frozenset iteration orders 跨 5 subprocess,
直接由 `actor_critic.py:258` `for kind in head_kinds:` 引入。1 LOC fix
(`for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):` +
1 LOC `_REGISTRY_ORDER` module 常量)+ 99 LOC subprocess-stress guard
test + spec A12.1 sub-invariant 治理 single source of truth(`HEAD_REGISTRY`
insertion order)。

post-fix:
- AZ smoke_full PASS(train + resume + ≥ 1 new ckpt,wall 59.5s)
- BC + CFR + DMC smoke_full no regression(PASS unchanged)
- PPO smoke_full skip 不动(其独立 pre-existing bug)
- AZ baseline 189 / 189 PASS
- Full training tests 999 passed / 3 skipped / 0 failed

## What we built

- `training/core/network/actor_critic.py`:
  - line 65-73:add `_REGISTRY_ORDER` module-level dict + inline comment
    解释 ckpt resume invariant 依赖(A12.1)
  - line 263-269:replace `for kind in head_kinds:` →
    `for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):`
    + inline A12.1 rationale comment
- `training/tests/test_head_order_deterministic.py` NEW(99 行):
  - `_DUMP_SCRIPT` subprocess builds `make_actor_critic(cfg, kinds)` +
    print `','.join(net.heads.keys())`
  - `_stress_head_order(mod_path, kinds_name, n=3)`:跑 n=3 fresh
    subprocess(env 清 `PYTHONHASHSEED`),assert n=1 unique order
  - 3 tests:AZ / BC / PPO head sets(DMC 单 head 不需要 cover)
- `training/tests/test_az_smoke_full.py`:
  - removed `@pytest.mark.skip(reason='az-resume-shape-fix')` decorator
  - 改写 docstring:删 STATUS-FAIL 段(bug 已修),改记 POST archive
    状态 + 2 prior follow-up history pointers(`az-pool-spec-type-fix`
    解锁 train-phase,本 change 解锁 resume-phase)
- `openspec/specs/network-architecture/spec.md`:
  - SHALL 12(Generic ActorCritic composition)后追加 **A12.1** sub-invariant
    (≤ 18 行),含 canonical iteration form + guard test pointer
  - Status section +Revised entry

## Tradeoffs revisited

- **Option A(sort by `HEAD_REGISTRY`)vs Option B(sorted alphabetical)
  vs Option C(改 caller `frozenset` → `tuple`)vs Option D(改
  `CheckpointManager` per-name optimizer state)**:预期 A / 实际 A ✓ —
  `HEAD_REGISTRY` 是 single source of truth(invariant 12 已 anchor),
  显式 canonical;alphabetical(B)虽然也 deterministic 但 implicit;
  改 caller(C)破 `frozenset` closed-set 语义 + 5 paradigm 散布;
  改 ckpt schema(D)scope 不成比例(`optimizer.state_dict()` PyTorch
  native is positional,引 name mapping 是 ad hoc layer)。
- **加 `_REGISTRY_ORDER` 常量 vs 内联**:预期 + 实际 module 常量 ✓ —
  避免每次 `make_actor_critic` 调用重 build dict;常量定义紧邻
  `HEAD_REGISTRY`,易 single-glance review;sort key
  `_REGISTRY_ORDER.__getitem__` 更便利 than 内联 lambda。
- **guard test 不 mark smoke**:预期 default unit tier / 实际 default unit
  tier ✓ — 3 subprocess × 3 paradigm = ~5s wall,well under smoke 60s
  budget;但本质 invariant guard 而非 smoke(无 collector / forward /
  backward),纳入 default suite 更合 invariant guard 语义。
- **不补救已 saved 的 broken ckpt**:预期 + 实际 不补救 ✓ —
  AZ resume 在此 bug 存在期间是 完全 broken 的(任何 ckpt resume 都
  失败),无 in-the-wild 受影响 ckpt;新 ckpt(本 change 后 save 的)
  跨 process resume 自动 deterministic;backward-compat 无 case。

## Surprises

- **直接 reproduce 不够 — 必须 mimic pipeline exactly**:第一版 diag test
  build network + save + load + step 在 same process 全 PASS。第二版必须
  subprocess train + 另一 process load 才 reproduce — 这才暴露 cross-
  process state ordering 才是 root cause,而 not "any save / load 流程"。
  这反向证明 hypothesis A(dynamic param shape)不成立,推动 hypothesis C
  (set iteration determinism)。
- **frozenset 是 hidden 非 determinism source**:CLAUDE.md 没显式禁
  frozenset iter,但 ckpt resume 用例下它就是 bug 来源。spec A12.1 显式
  治理 — 类似的 trap 在 dict iteration 直到 Python 3.7 才解决;set /
  frozenset 至今 PYTHONHASHSEED=random 不可避免。Future spec audit
  应加 "iteration over set / frozenset in ckpt-relevant path = 反 pattern"。
- **PPO_HEAD_KINDS 也 cover**:虽然 PPO smoke_full 独立原因 skip,
  guard test 仍 cover(deterministic head order 是 invariant,与
  smoke_full path 是否启用解耦)。BC / PPO / AZ 都用 `frozenset` 同形,
  对称 cover 防 future PPO unblock 又中招。
- **DMC 单 head 因祸得福**:DMC `frozenset({'q'})` 单 head 让它
  smoke_full 早就 PASS。但若未来 DMC 加 second head(eg. `'value'` for
  TD target),会立即触同 bug — A12.1 spec 把这条护栏 surface 在
  invariant 层,而非依赖 "1-element frozenset 没 iter 歧义" 的偶然
  豁免。
- **archive 时间 sweet spot**:fix 本身 5 LOC,但 4 distinct iteration
  orders × 5 subprocess 的实测数据(diag step 4)是最强的 root cause
  证据 — 写入 design retrospective 防 future 重判。

## Spec delta summary

本 change 修订 **1 个 capability spec**(network-architecture):

- **network-architecture/spec.md §3 SHALL 12**:
  - **ADD sub-invariant A12.1** — `make_actor_critic` SHALL iterate
    `head_kinds` in `HEAD_REGISTRY` insertion order;canonical form
    `sorted(..., key=_REGISTRY_ORDER.__getitem__)`;guard test 引用
  - **Status +Revised**:2026-05-17 entry(本 change archive)

合并后行数:241 → 265(+24),仍 << 阈值(本 spec 无显式行数硬阈值,
作为 large reference spec 容纳)。

## DECISIONS index

无独立 DECISIONS 文件(极轻量 follow-up,所有决策 inline 本 retrospective):

- D1:Option A(`HEAD_REGISTRY` order)vs B(alphabetical)vs C(caller
  改 tuple)vs D(改 ckpt schema)→ A
- D2:`_REGISTRY_ORDER` 常量 vs 每次 build dict → 常量(性能 + 紧邻
  registry 易 review)
- D3:guard test 不 mark smoke → default unit tier(invariant guard 不是
  smoke 语义)
- D4:guard test cover AZ + BC + PPO,不 cover DMC → 单 head 无歧义,
  但 spec A12.1 仍治理(防 DMC 未来加 head)
- D5:不补救已 saved broken ckpt → 此 bug 期间 AZ resume 完全 broken,
  无 in-the-wild ckpt
- D6:diag 用 subprocess-stress 实测 frozenset iteration order 不一致
  (4/5 distinct)— 写入 design retrospective 作 root cause 唯一证据
