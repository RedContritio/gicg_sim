---
last_updated: 2026-06-12
status: LIVE
schema_version: 0
parent: ./spec.md
---

# File structure — data/pools/ 目录布局 + 加载顺序 + 自包含约定

> 治理 [`./spec.md`](./spec.md) invariant #1(DSL 加载)+ #13
> (Declare-or-get positional)文件层面的实施约束。本 subtopic 规定
> data/ 树形组织、加载顺序、与文件自包含原则;不重复 engine-runtime
> 拓扑算法 spec(详 cross-ref)。

## 1. Pool 布局根

ADR-0011 落地后,所有 DSL files SHALL live under `data/pools/<pool_id>/`
(详 `openspec/changes/archive/0011-pool-versioning/`)。

- `<pool_id>` SHALL 唯一标识一个卡池版本(例 `v_legacy` / `test_basic` /
  `spike` / `v_phase2_*`)
- 每个 pool 根 SHALL include a `manifest.toml` declaring parent pool +
  override / remove rules
- Loader SHALL walk the parent chain in `manifest.toml`,fold overrides
  和 removes,产出最终文件集合

## 2. Per-pool 三段式 layout

每个 pool 根 SHALL include 以下三个子目录(空目录允许):

```
data/pools/<pool_id>/
  characters/    -- 角色 DSL(meta + skill + buff)
  cards/         -- 卡牌 DSL,按 L1-L6 难度分层
  system/        -- 系统级 DSL(reaction / round / alive / element 等)
  manifest.toml  -- pool 元数据(parent / 覆盖 / 移除)
```

## 3. characters/ 子树

每个角色 SHALL 独占一个子目录 `characters/<name>/`,包含以下文件:

- `<name>.lua` — 角色元数据(HP / 能量上限 / 元素 / 武器),SHALL be the
  only file calling `declare_char` / `bind_char` 对该角色
- `<name>_<skill>.lua` — 单技能基础效果(`declare_skill` + 伤害
  pipeline);SHALL NOT 包含角色 buff 状态(归 buff 文件)
- `<name>_<buff>.lua` — 单个 buff 拥有其所有相关 effects(附魔 / 加伤 /
  衰减 / 治疗条件 etc.;详 `memory feedback_buff_owns_effects`)

例:

```
characters/赤蝶/
  赤蝶.lua        -- declare_char + bind_char
  赤蝶_枪.lua     -- declare_skill("枪") + damage
  赤蝶_蝶火.lua   -- 附魔 / 加伤 / 衰减(buff 拥有全部效果)
  赤蝶_回火.lua   -- 治疗条件 + on_round_end
```

## 4. cards/ 子树

卡牌 SHALL be organized into `cards/L{1..6}/` subdirectories,每文件
一张卡:

```
cards/L1/碌碌无为.lua          -- L1: 无效果,纯填充
cards/L3/以牙还牙.lua          -- L3: 多步追踪
cards/L5/守正.lua              -- L5: 改写角色技能
```

L1-L6 是 curriculum 维度的难度分级(服务训练课程设计,非 spec 性内容);
详 `docs/3_plans/cards/card_difficulty_grades.md`。

## 5. system/ 子树

系统级 DSL SHALL contain global mechanics 文件,典型集合:

```
system/
  reactions/
    蒸发.lua  超载.lua  融化.lua  感电.lua
    冻结.lua  超导.lua  结晶.lua  解冻.lua
  round.lua       -- AP counter / 回合开始 AP 重置 / 先手判定
  alive.lua       -- 死亡检测(on_after_write(HP, SUB))→ 强制切换
  element.lua     -- 元素附着 counter 系统
  frozen.lua      -- on_action_check 检查冻结 → 阻止技能 / 切换
  reaction.lua    -- 反应调度入口(派发到 reactions/ 文件)
  draw.lua        -- 开局抽 5 / on_round_end_final 抽 2
  timeout.lua     -- 第一回合先手记录 / round-limit 判负
  food.lua        -- 饱腹 counter / 食物再用阻止
  equip.lua       -- 装备 counter 基础设施
  dice.lua        -- (ADR-0019)dice / element-cost 系统
  arche.lua       -- (ADR-0019 §A.3 Phase 1)Arkhe enum + marker counter
```

新加 system 文件 SHALL 在 `gicg_engine/capi/capi_init.go` `systemFiles`
slice 中追加(详 §6)。

## 6. 加载顺序

CAPI loader(`gicg_engine/capi/capi_init.go`)SHALL load 文件按以下分组
顺序(detail per group):

1. **System files**(group 1)— SHALL load in the **fixed order** declared
   in `systemFiles` slice;reactions/ 子目录按 `os.ReadDir` 字典序追加,
   然后 `reaction.lua` 调度入口最后(必须在所有 reaction 文件之后)
2. **Character meta files**(group 2)— `characters/<name>/<name>.lua`
   SHALL load per-binding(slot-aware via `bind_char`);mirror match
   场景中同名角色 SHALL 分别按 binding 加载(详
   [`./skill-pattern.md`](./skill-pattern.md) "mirror filter")
3. **Character skill / buff files**(group 3)— `characters/<name>/<name>_*.lua`
   SHALL load per-binding,after the corresponding `<name>.lua`
4. **Card files**(group 4)— `cards/L*/*.lua` SHALL load **globally** via
   `Runtime.LoadFilesWithDeps` 拓扑排序一次,跨 mirror binding 共享
   ref(详 [`./skill-pattern.md`](./skill-pattern.md) "talent shared-load")

详 cross-ref:
- Topological sort 算法 — `openspec/specs/engine-runtime/spec.md`
  `Runtime.LoadFilesWithDeps`
- Per-binding char 加载 — `openspec/specs/engine-capi/spec.md`
  init pipeline

## 7. 文件自包含约定

每个 DSL 文件 SHALL be self-contained:

- File 顶部 SHALL `declare_counter` / `get_counter` 自己需要的 handle
  (declare-or-get 模式,详 [`./counter.md`](./counter.md))
- SHALL NOT 依赖某个集中的 "counters.lua" 共享文件
- 跨文件共享 counter / skill / card SHALL only through declare-get
  protocol(同名同 scope 第二次 declare 返回已有引用)
- SHALL NOT 通过全局变量 / `_G.*` / shared lua tables 跨文件传递 state
  (详 [`./builtin-api.md`](./builtin-api.md) §1.2 forbidden constructs)

例:`赤蝶_蝶火.lua` 和 `赤蝶_回火.lua` 各自 `declare_counter("蝶火_active",
Scope.Self, 0, {min=0, max=1})` 引用同一 counter;`declare_skill(赤蝶,
"枪", 3)` 返回已有枪的 `SkillRef`,可用于注册加伤 hook。

## 8. char-skill 静态扫描约束

`characters/<name>/<name>_*.lua` SHALL NOT call `get_card("X")` —
topo loader 静态扫描要求 char skill 文件不能反向引用 card(architectural
constraint;详 `memory feedback_char_skill_no_get_card`)。

反向引用 SHALL 通过 `sharedFiles` 模式从 card 文件引用 char(`requires_char`
marker)实现。

## 9. Topo loader fail-loud(F3)

交给 topo loader(`Runtime.LoadFilesWithDeps` / `topoSortWithMeta`)的
文件 SHALL 全部可加载:任一文件的依赖(`get_counter` / `get_char` /
`get_skill` / `get_card`)不可解析 —— 直接缺失,或 provider 文件自身
broken —— 时 SHALL 在构造期报错,错误信息 SHALL 列出每个 broken 文件
与缺失符号。Loader SHALL NOT 静默剔除不可解析文件(历史事故:以逸待劳
的 "ap" counter 依赖在 AP 系统移除后失效,整卡静默消失,跨 session
无人察觉)。

依赖扫描 SHALL 为 comment-blind:regex 跑在原始 src 字节上,注释中的
`get_counter("X")` 字面文本同样计入依赖。声明级 optionality(如
`requires_char` talent 预过滤)SHALL 位于 topo 上游(文件集合构造时,
`factory.FilterTalentCardsForSlotUniqueness`),不在 topo 内。

契约测试:`gicg_engine/interp/loader_topo_test.go` +
`gicg_engine/tests/pool_load_guard_test.go`。

## 10. Cross-reference

- Counter declare-get 文件级模式详 [`./counter.md`](./counter.md) §1.4
- Skill pattern char-binding / mirror filter / talent shared-load 详
  [`./skill-pattern.md`](./skill-pattern.md)
- Builtin API 文件 sandbox 约束(`ExecFileSandboxed`)详
  [`./builtin-api.md`](./builtin-api.md) §1.3
- Runtime 加载算法详 `openspec/specs/engine-runtime/spec.md`
- CAPI 初始化 pipeline 详 `openspec/specs/engine-capi/spec.md`
- Pool 版本治理详 `openspec/changes/archive/0011-pool-versioning/proposal.md`
- Memory cross-refs:
  - `memory feedback_buff_owns_effects` — buff 拥有所有效果
  - `memory feedback_char_skill_no_get_card` — char skill 静态扫描约束
  - `memory project_pool_versioning` — ADR-0011 落地
