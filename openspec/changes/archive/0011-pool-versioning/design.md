# Design (retrospective)

## Consequences

### Pool 目录结构

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

### Manifest schema

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

### Override 语义(沿 parent 链 fold)

- **卡**:**文件级**,子池 `cards/<path>/<name>.lua` 覆盖父池同 `name` 的卡(身份 = `declare_card(name)`
  字符串,不靠路径)
- **角色**:**整目录**,子池 `characters/<name>/` 出现 = 完整替换父池同名角色目录(必须列全所有
  skill 文件)
- **Remove**:仅 `[cards].remove` / `[characters].remove` 显式声明
- **不引入 `base` 池**:目前 test_basic 与 v_legacy 无公共子集(`碌碌无为` 各放一份独立)

### Cfg 显式 deck_padding

```toml
[scenario]
card_pool = ["测试卡_碎片"]
deck_padding = { card = "碌碌无为", target_size = 15 }
```

`ScenarioConfig.deck_padding: Optional[DeckPadding]` (`card: str`, `target_size: int`);
`GameConfig.DeckPadding *DeckPaddingSpec`;`BuildDeck` 接 padding spec(nil → eligible 任意长度;否则
pad 到 target_size 用 `card`);loader 看到 padding 时自动把 padding card 加到 cardPool allow set
(确保被 declare 进 ruleset)。默认 = `None`(不 pad)。

### Pool cache

- 加 process-global `poolCache` `map[(dataDir, poolID)] → *PoolResolution`,follow `loader.go::dslCache`
  模式
- `PoolResolution.Chars` 升级为 `map[string]*PoolCharEntry` — 不再只存 dir,而预先 walk 出 `Declare`
  (`<name>.lua`) + `Skills`(其他 .lua, sorted)
- `capi_init.go::collectDSLPaths` 不再 ReadDir,完全从 cache 读
- 效果:**worker 进程第一次 GameNew 走完磁盘 + cache,之后整个 process lifetime 不触磁盘**。配合
  `DSLPreload` 在训练入口预热实现真正的内存加载
- 语义同 dslCache —— mid-run pool / manifest 编辑不被 picked up(documented limitation,符合 dslCache
  既有约定)

## Tradeoffs

| 维度 | 老 | 新 |
|---|---|---|
| Engine Ignorance | 违反(deck.go 认 "碌碌无为" 字符串) | 恢复(deck.go 不认任何具体卡) |
| Filler 行为来源 | 引擎隐式 hardcode | cfg 显式声明 |
| Deck 长度 | 强制 15 | 任意长度合法 |
| 卡池组织 | 全局命名空间 | pool 隔离 + parent 继承链 |
| Baseline 数据 | — | 100% 兼容(cfg 显式保旧行为) |

### Migration

- PR 一次性做完:引擎 + cfg + pool 重组
- 现存测试 / 训练 cfg 加显式 padding 字段保旧行为(实际通过 base preset 默认值集中声明)
- 后续新版本卡池(v3.3 等)按 manifest schema 增建,parent 指 v_legacy 或后续 prod 根池

### 已知 落地遗漏(memory `project_v_phase2_eval_schema_gaps`)

- `eval_service_schema` / `eval_bc_ckpt` 缺 pool / deck_padding 字段
- `framework.gauntlet` env 不稳;三个 silent fail 都未 commit fix
- P1+ 需 backfill 修复 + 写 spec SHALL

## References

- `docs/2_decisions/adr-0011-pool_versioning.md` (mirror)
- `CLAUDE.md` Engine Ignorance 原则
- `docs/1_specs/engine/dsl/conventions.md`(P1 update 反映 pool 结构)
- `gicg_engine/interp/deck.go` — filler hardcode 来源(已删除)
- memory `project_pool_versioning` — 2026-04-28 PM ship summary
- memory `project_v_phase2_eval_schema_gaps` — 落地遗漏 backfill 任务
