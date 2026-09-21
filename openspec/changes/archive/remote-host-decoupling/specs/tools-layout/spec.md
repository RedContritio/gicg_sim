---
change_id: remote-host-decoupling
capability: tools-layout
delta_type: MODIFY
target_subtopic: (capability index)
---

# Spec Delta — tools-layout

> 本 change 只修订 `openspec/specs/tools-layout/spec.md` 的 §Remote workflow
> (不变量 #17)并追加 #22–#25。§Directory boundaries 与 §Historical boundary
> 不动。
>
> 修订动机见 [`../../proposal.md`](../../proposal.md):`[remote]` 段四个字段全为
> 设备级,却被逐 cfg 抄了 14 份。设计见 [`../../design.md`](../../design.md) §1。

## [MODIFY] Invariant 17 — remote 执行的 config-driven 定义

**Before**:

```
17. Remote execution SHALL be config-driven through `[meta].host = "remote"`
    and a `[remote]` section. `tools.runs.train` SHALL auto-sync and forward the
    lifecycle when the configured hostname is not local.
```

**After**:

```
17. Remote execution SHALL be config-driven through `[meta].host = "remote"` and
    a `[remote].profile` name resolving to the git-ignored host registry, which
    carries the device's connection fields and its single project root.
    `tools.runs.train` SHALL auto-sync and forward the lifecycle when the
    configured hostname is not local.
```

**Rationale**: 原表述把 `[remote]` 段当作不透明的四字段块。实测 14 个带
`[remote]` 的 cfg 曾出现 5 种 `root`,但那**不是** `root` 属于 cfg 级字段的证据,
而是执行期漂移:`tools.runs.list` / `tools.runs.show` 扫的是
`<repo_root>/artifacts/`,`allocate_nnn` 的计数器与锁亦以 `<repo_root>/artifacts`
为域,而 `artifacts/` 不参与同步——故每个项目根各持一套 run 索引与 NNN 计数器,
多根本身就会让 NNN 跨根重复、`show <NNN>` 失效。四字段同为设备级,故一并移出。

## [ADD] Invariant 22 — 设备标识的唯一边界

```
22. Machine-identifying remote values (`ssh`, `os`, `hostname`, `root`) SHALL
    reside only in the git-ignored registry `configs/hosts/hosts.toml`, keyed by
    profile name. The repository SHALL ship `configs/hosts/hosts.example.toml`
    carrying placeholder values only, and SHALL NOT carry real values in any
    tracked file.
```

**Rationale**: 只规定"值放哪里"不足以防回归——必须同时规定追踪物只含占位符,
否则新增 cfg 时仍可能把真实值写进 `[remote]`。`hosts.example.toml` 是必备的,
它承担新 clone 的形状说明职责,并与 §23 的 fail-loud hint 配合。`root` 列入本
不变量,是因为它同样定位到具体设备 `<root> = "D:/gicg_dev"`。

## [ADD] Invariant 23 — 解析失败必须可见

```
23. Resolving a remote host profile SHALL fail loudly — raising — when the
    registry file, the named profile, or any required field is absent or
    invalid. Resolution SHALL NOT fall back to local execution.
```

**Rationale**: 注册表在仓库之外,存在"文件没建 / 名字打错"的常见失误。若这些
情况静默退化为本地执行,一次本应在 56 上跑数小时的训练会在 Mac 上静默跑起来
且无人察觉。fail-loud 是这一外置设计成立的前提。

## [ADD] Invariant 24 — 注册表随同步到远端

```
24. `tools.runs._remote_sync._auto_sync` SHALL include the host registry file in
    the path list it pushes, so the remote box resolves the same profile and its
    own `is_local_host` check succeeds. This single injection point covers both
    the initial full sync and the incremental sync; it is the sole sync path used
    in production (`tools.runs.train` and `tools.runs.build_engine` both route
    through it).
```

**Rationale**: `tools.runs.train` 把 cfg 路径本身转发到远端重跑,远端会再解析
一次 profile。若不随之同步注册表,远端按 §23 直接 raise,远端派发路径整体失效。
注册表是 gitignored 的,而 `_auto_sync` 的两条子分支都由 git 派生文件列表
(`git ls-files` / `git diff`),天然不含它,故必须在构造 `paths` 处显式并入。
`--tar-all` 无需改动——它按 `REPO_DIRS` 做目录遍历,注册表本就在内;`--single`
的契约是"只推指定文件",不得并入第二个文件。

## [ADD] Invariant 25 — 每设备唯一项目根

```
25. A remote device SHALL have exactly one project root, and it SHALL be the
    `root` value of that device's registry profile. Isolation between
    experiments SHALL be provided by cfg parameters and per-run
    `artifacts/<ts>_<NNN>_<label>/` directories, never by opening an additional
    project root on the device.
```

**Rationale**: 每个项目根各自持有一套 `artifacts/` 索引与 NNN 计数器(二者都以
`<repo_root>` 为域,且不参与同步),故多根并存会让 NNN 跨根重复、
`tools.runs.show` 的 shorthand 不再唯一。历史漂移的机制是"每次源码状态大改就另开
目录以免覆盖正在跑的 run"(见 `docs/5_history/handoff_20260914_part1.md:75`、
`docs/5_history/cards/native_first_batch_audit.md:253`、
`docs/5_history/cards/consequence_policy_rl.md:21`),实测出现过 5 个根。用户已手工
收敛到 `D:/gicg_dev`;本不变量防止回归。仓库内此前**没有任何一处**记录过这条约定,
故此为本 change 首次成文。

## [REMOVE] 无

本 change 不删除任何既有 SHALL。`ALLOWED_TOP_LEVEL` 中的顶层 `remote` 段名保留
(design.md §T1:删除它会触发 `fingerprint()` 变更,收益仅为少一行允许列表)。
