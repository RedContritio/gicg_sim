---
last_updated: 2026-05-12
status: HISTORICAL BACKLOG — 2026-05 v_phase2 snapshot
---

# v_phase2 池 deferred 机制 backlog

> **历史 backlog**：本文记录旧 `v_phase2` 池的简化项，不是当前原生
> 内容接入清单。后续内容审核见
> [`cards/native_content_curriculum.md`](cards/native_content_curriculum.md)。

> 跨 session 工程清单。v_phase2 池建立后 (commit `9969f2e`),为加速 RL smoke 验证,
> 所有 status / summon / 条件 buff / prepare_skill / 复杂状态机机制 lua 都标
> `-- TODO` 留为 deferred,只实现"造 X 元素伤害"基础部分。本文档列完整 23 项
> + 分 4 batch,每项需 cleaned 数据严格对照 + 配套 spike test + 字段不偏移。
>
> **入口前置**:`docs/0_status/dsl_v6_progress.md` 已 ship 的 DSL hook 清单;
> `data/pools/v_phase2/characters/*/.lua` + `data/pools/v_phase2/cards/*/*.lua`
> 头部 `deferred:` 注释列每张角色/卡的缺失机制。

## standard (重申)

每个机制实现:
1. lua 头部 `source: data/cleaned/...yaml` 路径 + 字段对照行
2. HP / energy / cost / element / 数值字段强制对照 cleaned,任何偏离 fail
3. spike test 锁 cleaned 数值 + 行为路径
4. 简化的部分必须在 lua 注释 + commit msg 明说 deferred 哪些 sub-机制

## 23 项 deferred (按 batch)

### Batch 1 — 无依赖最简单 (7 项, ~250 LOC + spike test)

| # | 机制 | 类型 | LOC 估 | 备注 |
|---|---|---|---|---|
| 1 | 砂糖-大型风灵 | Summon | ~40 | 结束阶段 2 风, usage 3, 扩散变更元素 (后者 deferred,本项只做 2 风 + usage) |
| 2 | 柯莱-柯里安巴 | Summon | ~40 | 结束阶段 2 草, usage 2 |
| 3 | 凯亚-寒冰之棱 | Combat Status | ~35 | on_switch 触发 2 冰, usage 3 |
| 4 | 凝光-璇玑屏 | Combat Status | ~45 | 出战受≥2 抵 1, usage 2 (declare_shield builtin) |
| 5 | 凝光-天权崩玉 +2 | 条件 buff | ~10 | 璇玑屏在场 → 本伤害 +2 (依赖 #4) |
| 6 | 派蒙 完整 | 卡 status | ~10 | 现 lua "持续 2 回合" → 改 "usage 2 用完弃置" |
| 7 | 鸣神大社 完整 | 卡 status | ~30 | 现 lua "技能后无条件 +1" → 改 "骰子总数为奇数 +1, 每回合 2 次" |

**Pattern 参考**: `data/pools/v_legacy/characters/天星/天星_岩脊.lua` (Summon),
`data/pools/v_legacy/characters/猫咪/猫咪_甜美领域.lua` (Combat Status)。

### Batch 2 — 克洛琳德 状态机链 (4 项, ~250 LOC + spike test)

| # | 机制 | 类型 | LOC 估 | 备注 |
|---|---|---|---|---|
| 8 | 克洛琳德-生命之契 status | char status | ~50 | 可叠加无上限, 受治疗按数消耗 (on_before_heal) |
| 9 | 克洛琳德-夜巡 status | Combat Status | ~80 | 1 回合, 治疗→契 (cancelHealed), 普攻物理→雷 + 自附 2 契 |
| 10 | 克洛琳德-狩夜之巡 完整 | skill | ~50 | 附夜巡 + 移除契计 N → 造 N 雷 (≤4) + 治 N (≤4) |
| 11 | 克洛琳德-逐影之誓/残光将终 | skill | ~50 | 残光附 4 契 + 逐影附夜巡时物理→雷 (依赖 #8 + #9) |

依赖: #10/#11 都依赖 #8 + #9 先做。

### Batch 3 — 坎蒂丝 + 砂糖 (3 项, ~200 LOC + 2 个 builtin 可能)

| # | 机制 | 类型 | LOC 估 | 备注 |
|---|---|---|---|---|
| 12 | 坎蒂丝-赤冕祝祷 | Combat Status | ~70 | 普攻+1 / 物理转水 / 切换造 1 水 (持续 2 回合) |
| 13 | 坎蒂丝-苍鹭护盾 + 苍鹭震击 | Prepare Skill | ~80 | 战技附盾 + 准备技能 (ADR-0012) |
| 14 | 砂糖-风灵作成·陆参零捌 强制切换 | builtin | ~40 | 需 force_switch DSL builtin (engine 已有 ActSwitch?) |

### Batch 4 — 玛薇卡 整套 (5 项, ~400 LOC, 最复杂)

| # | 机制 | 类型 | LOC 估 | 备注 |
|---|---|---|---|---|
| 15 | 玛薇卡-战意 (重定义 energy) | passive | ~80 | 不获充能, 消夜魂/普攻后 +1 战意 (energy → 战意 计数器) |
| 16 | 玛薇卡-诸火武装·焚曜之环 | Combat Status | ~60 | 其他角色普攻/特技后, 消 1 夜魂 → 1 火 |
| 17 | 玛薇卡-死生之炉 | Combat Status | ~40 | 普攻+1 + 不消夜魂, usage 2 |
| 18 | 玛薇卡-驰轮车 跃升/涉渡/疾驰 | Specialty Card | ~80×3 | 3 张 specialty 手牌, ADR-0012 prepare_skill |
| 19 | 玛薇卡-称名之刻 完整 | skill | ~30 | 生成 1 张驰轮车 + 附焚曜之环 (依赖 #15 #16 #18) |

### 其它 (不归 batch)

| # | 机制 | 备注 |
|---|---|---|
| 20 | 玛薇卡-燔天之时 消耗 6 战意 → 死生之炉 | 依赖 #15 + #17 |
| 21 | 旅行剑 / 魔导绪论 talent 条件 buff | 没有 talent 卡录入,不属于当前 6 张代表;后续录入 talent 卡时再做 |
| 22 | 凝光-璇玑屏 talent | 同上 |
| 23 | 砂糖-大型风灵 扩散反应变元素类型 | #1 简化版仅 2 风, 后续若引入扩散触发再扩 |

## 工作总量

- 23 项 × 平均 ~50 LOC = **~1100 LOC lua**
- 配套 spike test ~700 LOC
- 可能 2 个新 DSL builtin (force_switch / prepare_skill 扩展)
- **总 ~1800-2500 LOC**

## 推进节奏

每 batch commit 一次。建议:
1. 单 session 做 1 batch (Batch 1 / Batch 2 各约 1-2 小时)
2. Batch 之间 user review + 调整方向
3. Batch 4 (玛薇卡) 工作量最大,可拆 sub-batch

完成所有 batch 后,跑 RL smoke 验证 — 此时 cleaned 数据完整还原,
RL agent 应能学到真实七圣召唤策略 (不是 deferred 简化版)。

## 当前 v_phase2 状态 (commit d011859 后)

- ✅ 7 character (火-玛薇卡 / 水-坎蒂丝 / 雷-克洛琳德 / 草-柯莱 / 冰-凯亚 / 岩-凝光 / 风-砂糖)
- ✅ 6 卡 (装备 2 + 事件 2 + 支援 2)
- ✅ field-lock spike test (cleaned 数值锁)
- ✅ Python GicgEnv 加载 (9 pytest)
- ✅ RL smoke 20 game / 4 ckpt 落盘 (artifacts/202605120541_v_phase2_smoke/)
- ⚠ 简化机制 23 项 deferred (本文档)

## 关键文件路径

| 路径 | 内容 |
|---|---|
| `data/pools/v_phase2/characters/<name>/<name>.lua` | 角色 主 lua (HP/energy/element/weapon) |
| `data/pools/v_phase2/characters/<name>/<name>_<skill>.lua` | 单 skill lua + deferred 注释 |
| `data/cleaned/character/<id>_<name>.yaml` | mihoyo 数据权威源 (英文 schema, cli.py --keys en 产物) |
| `gicg_engine/tests/v_phase2_kaeya_field_lock_test.go` | 7 角色字段锁 (表驱动) |
| `gicg_engine/tests/v_phase2_cards_field_lock_test.go` | 6 卡字段锁 |
| `configs/v_phase2_smoke.toml` | RL smoke cfg (凯亚 mirror 1v1) |
