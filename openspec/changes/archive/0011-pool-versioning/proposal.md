# Pool versioning + filler 引擎依赖移除

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0011-pool_versioning.md` at P1-T1)
**Original date:** 2026-04-28 PM
**Original status:** Accepted (shipped via PR)
**Supersedes:** —
**Superseded by:** —

## Why

两个独立但 coupled 的问题:

**P1 — 卡池版本管理需求**:`data/{cards,characters}/` 单一全局命名空间,无法表达:
- 测试 fixture vs 正式卡池的隔离
- 同一张卡的版本演变(引入版本、平衡性 patch)
- 多个游戏版本之间的 deck 配置切换

**P2 — Engine Ignorance 违反**:`gicg_engine/interp/deck.go:56` 含 `if n == "碌碌无为"` 字符串字面量,
把特定 DSL 卡硬编码进 Go engine,违反 CLAUDE.md "Engine Ignorance" 原则。`capi/capi_init.go:53`
同样 hardcode `fillerCardName = "碌碌无为"` 强制载入。`BuildDeck` 借此 pad 短 deck 到 DeckSize=15。

下游影响:54 个训练 cfg(`s064-068`、`r010-012`、`s069`、历史 `s028-052`)用 `card_pool=["测试卡_碎片"]`
默认依赖 filler pad 到 15 张 deck,RL closure baseline 数据建立在该行为上。

## What

合并一个 PR 同时解决两问题,不破坏现存 baseline:

1. **Pool 目录式版本(P1)** — `data/pools/<id>/manifest.toml` + `cards/` + `characters/`;parent
   链 fold(base→leaf);override 语义(卡文件级 / 角色整目录 / `[cards|characters].remove`);
   不引入 `base` 池(test_basic 与 v_legacy 无公共子集)
2. **引擎层移除 filler hardcode(P2)** — 删 `capi_init.go:53` const、`interp/deck.go:56` 字面量、
   `BuildDeck` pad 逻辑、`capi_init.go:138` 强制载入;空 deck graceful (`game_shuffle.go:155` 已支持)
3. **Cfg 显式 `deck_padding`(P2 兼容层)** — `[scenario]` 加 `deck_padding = { card, target_size }`;
   `ScenarioConfig` / `GameConfig` 加字段;`BuildDeck` 接 padding spec(nil → 任意长度;否则 pad);
   loader 自动把 padding card 加到 cardPool allow set
4. **Cfg 0-修改保 100% bit-exact baseline(实际方案)** — 在 **base preset / TrainingConfig 默认值**
   层面集中声明,cfg 自动继承;`smoke_config()` / `PPOConfig` 默认 `deck_padding = {"碌碌无为", 15}` +
   `pool = ["v_legacy", "test_basic"]`;测试 helper / web backend 同步
5. **Pool 字段支持 sibling union(实际方案)** — `GameConfig.Pools` 是 `[]string`(JSON `pools`);
   Python 接 `str | list[str] | None`;v_legacy + test_basic 双池 union(legacy cfg 跨池引用兼容);
   未来真正按版本拆 pool 时 prod cfg 应 pin 单一 pool ID
6. **Pool resolution 走内存 cache(脱耦磁盘)** — `poolCache` `map[(dataDir, poolID)] → *PoolResolution`,
   follow `loader.go::dslCache` 模式;`PoolResolution.Chars` 升级 `map[string]*PoolCharEntry`(预先 walk
   出 Declare/Skills);worker 进程第一次 GameNew 走完磁盘 + cache,之后整 process lifetime 不触磁盘

## Affected specs

- `engine-pool` (待建,P1-T2/T6 抽 SHALL invariants 时 backfill)
- `engine-deck` (BuildDeck contract 变更)
- `cfg-schema` (`deck_padding` / `pool` 新字段)
- `engine-loading` (pool resolution + dslCache 一致性)
