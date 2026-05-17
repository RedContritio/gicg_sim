# ADR-0011: Pool versioning + filler 引擎依赖移除

> **MOVED to `openspec/changes/archive/0011-pool-versioning/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0011-pool-versioning/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0011-pool-versioning/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**Date:** 2026-04-28 PM
**Status:** Accepted
**Decided by:** 用户提出引入正式版本全量卡牌 + 版本管理需求,过程中发现 `碌碌无为` filler hardcode 违反 Engine Ignorance,合并清理

## Context

两个独立但 coupled 的问题:

**P1 — 卡池版本管理需求**
当前 `data/{cards,characters}/` 单一全局命名空间,无法表达:
- 测试 fixture vs 正式卡池的隔离
- 同一张卡的版本演变(引入版本、平衡性 patch)
- 多个游戏版本之间的 deck 配置切换

**P2 — Engine Ignorance 违反**
`gicg_engine/interp/deck.go:56` 含 `if n == "碌碌无为"` 字符串字面量,把一张特定 DSL 卡硬编码进 Go 引擎,违反 CLAUDE.md "Engine Ignorance" 原则(engine 不应知道任何具体卡)。`capi/capi_init.go:53` 同样 hardcode `fillerCardName = "碌碌无为"` 强制载入。BuildDeck 借此 pad 短 deck 到 DeckSize=15。

下游影响:54 个训练 cfg(`s064-068`、`r010-012`、`s069`、历史 `s028-052`)用 `card_pool=["测试卡_碎片"]` 默认依赖 filler pad 到 15 张 deck,RL closure baseline 数据建立在该行为上。

## Decision

合并一个 PR 同时解决,不破坏现存 baseline:

### 1. Pool 目录式版本(P1)

```
data/
  pools/
    test_basic/                  # 测试 fixture 池
      manifest.toml
      cards/...                  # 测试卡_*
      characters/测试角色*/
    v_legacy/                    # 当前 prod 卡 + 角色暂归此池
      manifest.toml
      cards/L1..L6/
      characters/{赤蝶,墨客,猫咪,刻师傅,天星}/
    # 后续按真实游戏版本拆 v3.3 / v3.4 / v4.1 / ...
  system/                        # 不进 overlay,保持全局共享
```

**Manifest schema**(`pools/<pool>/manifest.toml`):
```toml
[version]
id      = "v_legacy"
parent  = null              # null = 根池
desc    = "测试期遗留卡 + 5 个 prod 角色,占位用,待真正游戏版本拆分"

[cards]
remove  = []                # 仅显式 remove 必填

[characters]
remove  = []                # 整角色 remove
```

**Override 语义**(沿 parent 链 fold,base→leaf):
- 卡:**文件级**,子池 `cards/<path>/<name>.lua` 覆盖父池同 `name` 的卡(身份 = `declare_card(name)` 字符串,不靠路径)
- 角色:**整目录**,子池 `characters/<name>/` 出现 = 完整替换父池同名角色目录(必须列全所有 skill 文件)
- Remove:仅 `[cards].remove` / `[characters].remove` 显式声明
- 不引入 `base` 池(目前 `test_basic` 与 `v_legacy` 无公共子集 — `碌碌无为` 各放一份独立)

### 2. 引擎层移除 filler hardcode(P2)

- 删 `gicg_engine/capi/capi_init.go:53` `const fillerCardName = "碌碌无为"`
- 删 `interp/deck.go:56` `if n == "碌碌无为"` 字面量逻辑
- 删 `BuildDeck` 的 pad 逻辑(短 deck 直接合法,长度 = eligible 数)
- 删 `capi_init.go:138` `allowed[fillerCardName]=true` 强制载入
- 引擎 graceful 处理空 deck 已存在(`game_shuffle.go:155` `DrawCard` empty deck 直接 return)

### 3. Cfg 显式 deck_padding(P2 兼容层)

把"pad 到 15 张 filler"行为从隐式引擎机制提到 cfg 显式声明:

```toml
[scenario]
card_pool = ["测试卡_碎片"]
deck_padding = { card = "碌碌无为", target_size = 15 }
```

- `ScenarioConfig` 加 `deck_padding: Optional[DeckPadding]`(`card: str`, `target_size: int`)
- `GameConfig` 加 `DeckPadding *DeckPaddingSpec`
- `BuildDeck` 接受 padding spec:nil → deck=eligible(任意长度);否则 pad 到 `target_size` 用 `card`
- loader 看到 padding 时,把 padding card 自动加到 cardPool allow set(确保被 declare 进 ruleset)
- 默认 = `None`(不 pad,deck=eligible)

### 4. Cfg 0-修改保 100% bit-exact baseline(实际方案)

实施时发现:让每个 cfg 文件显式声明旧默认会改 60+ 文件,且每次新加 cfg 都要记得带这两个字段。改成在 **base preset / TrainingConfig 默认值层面**集中声明,cfg 自动继承,显式 override 才生效:

- `training/az/config.py::smoke_config()` 默认 `deck_padding = {"碌碌无为", 15}` + `pool = ["v_legacy", "test_basic"]`(`fixed_1v1_config` / `random_1v1_config` 都基于 smoke_config build)
- `training/ppo/config.py::PPOConfig` 默认同上
- `gicg_engine/tests/helpers_setup_test.go` 测试 helper `testPools = ["v_legacy", "test_basic"]`,`NewGameWithDeck` 自动设 `DeckPadding={"碌碌无为", 15}`
- `web/backend/replay_api.py` / `live_api.py` 默认 union 双池(legacy replay yaml 跨池引用兼容)

零 cfg 文件修改,bit-for-bit 与旧引擎一致(同 RNG seed → 同 shuffle → 同 deck)。

### 5. Pool 字段支持 sibling union(实际方案)

`GameConfig.Pools` 是 `[]string`(JSON `pools`)而非单 string。Python `pool` 参数接受 `str | list[str] | None`。理由:旧 `data/{cards,characters}/` 是单一全局命名空间,引擎 walk 整树。Pool 重组后 prod (`v_legacy`) 与 test fixture (`test_basic`) 分两池,但绝大多数现有 cfg 既用 prod 角色又用测试卡(或反之),需要 union。

未来真正按版本拆 pool 时,生产 cfg 应 pin 单一 pool ID(如 `pool = "v3.3"`),不再 union。

### 6. Pool resolution 走内存 cache(脱耦磁盘)

ResolvePool 第一版每次 `GameNew` 调用都 walk 磁盘(`os.Stat` + `filepath.Walk` `pools/<id>/`),违背"加载到内存脱耦"的设计意图。

Fix:
- 加 process-global `poolCache` (`map[(dataDir, poolID)] → *PoolResolution`),follow `loader.go::dslCache` 模式
- `PoolResolution.Chars` 升级为 `map[string]*PoolCharEntry` — 不再只存 dir,而是预先 walk 出 `Declare`(`<name>.lua`)+ `Skills`(其他 .lua,sorted)
- `capi_init.go::collectDSLPaths` 不再 ReadDir,完全从 cache 读

效果:**worker 进程第一次 GameNew 走完磁盘 + cache,之后整个 process lifetime 不触磁盘**。配合 `DSLPreload` 在训练入口预热,实现真正的内存加载。语义同 dslCache —— mid-run pool / manifest 编辑不被 picked up(documented limitation,符合 dslCache 既有约定)。

## Tradeoffs

| 维度 | 老 | 新 |
|---|---|---|
| Engine Ignorance | 违反(deck.go 认 "碌碌无为" 字符串) | 恢复(deck.go 不认任何具体卡) |
| Filler 行为来源 | 引擎隐式 hardcode | cfg 显式声明 |
| Deck 长度 | 强制 15 | 任意长度合法 |
| 卡池组织 | 全局命名空间 | pool 隔离 + parent 继承链 |
| Baseline 数据 | — | 100% 兼容(cfg 显式保旧行为) |

## Migration

- PR 一次性做完:引擎 + cfg + pool 重组
- 现存测试 / 训练 cfg 加显式 padding 字段保旧行为
- 后续新版本卡池(v3.3 等)按 manifest schema 增建,parent 指 `v_legacy` 或后续 prod 根池

## References

- `CLAUDE.md` Engine Ignorance 原则
- `docs/1_specs/engine/dsl/conventions.md`(待 update 反映 pool 结构)
- `gicg_engine/interp/deck.go`(filler hardcode 来源)
- 实施 commit:本 PR
