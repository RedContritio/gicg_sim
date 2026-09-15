---
last_updated: 2026-09-14
status: HISTORICAL — 2026-05-07 ADR-0019 implementation record
---

# DSL v6 (ADR-0019) 完整 strict 实施落地

> **历史实施记录**（2026-09-15 自 `docs/0_status/` 移入）：本文保留 2026-05-07 的 ADR-0019 路线、提交和
> 当时待办。当前 DSL 契约以
> [`openspec/specs/engine-dsl/`](../../openspec/specs/engine-dsl/) 和
> [`engine-runtime`](../../openspec/specs/engine-runtime/) 为准。

## 关键路线史(避免再绕弯)

1. **早期误判**:把 v4 prototype `gicg_engine/v2/` 当生产引擎起点,推 ADR-0017/0018 重写路线
2. **关键纠正**:user 确认 **v1 是生产引擎**(`gicg_engine/` 主目录,damage.go 268 LOC + lua DSL),v4 prototype 是旁路验证从未上线
3. **dsl_gaps 实证**:`docs/3_plans/cards/dsl_gaps.md`(2026-04-30 706 yaml)真 ★★★ gap 仅 2 个(IsSpecialty / 始基反应)
4. **closure spike 证伪**(2026-05-04):lua DSL 不支持 closure return value(ast.go:51 + eval.go:6 + builtins_hook.go:120),find_char(predicate) 路线不可行 → enum-based
5. **v1 ↔ ref/genius-invokation 对照**(2026-05-04):clone Guyutongxue/genius-invokation TS 实现到 ref/(AGPLv3,完整官方卡池),反实证 §B-4 早期"引擎自动消耗"路线
6. **strict 决策**(2026-05-05):user "全部 strict",**不刻意保留兼容/fallback**;新方式不兼容可改写原来的

## 23 Commits 链(完整 strict + Phase 2 + Tune + RL obs adapt + Modifier log)

```
f4c231b  §B.2/§B.3c — RL pipeline obs adapt + Modifier log encoder (engine + Python)
30af6ed  §A.4 / dsl_gaps D3 调和 (Tune) hook
22cb8c9  §A.3 Phase 2 — 陆行岩本真蕈 状态机 + 水史莱姆 元素生命
3170810  §A.3 Phase 2 — 攻坚特化型机关·荒 + 始基反应闭环
363a8c8  §A.3 Phase 2 — 克洛琳德 角色 lua
6de5333  §B.5 残留清理 — 删 HookDamageBoost/Reduce enum + token + builtin
e353a84  §B.5 完整 strict — 删旧 HookDamageBoost/Reduce + DSL 全 audit migrate
945143d  §B.5 minimal — opt-in 6 新 hook 时机 (旧兼容)[已 superseded]
cb2414c  §B.3c obs encoder 集成 typed damage + prepare-skill
4398450  §B.4 declare_shield builtin (DSL macro)
e6773c1  §A.3 Phase 2 minimal — buff-owned arche mechanism spike
c51d685  §B.3b recent_damage ring + SkillIdentityOf 反查
de99acc  §C.1 ADR-0012 status PROPOSED → ACCEPTED
669456b  §B.3a reaction declare registry + ctx.reaction_kind
2c2c60d  §A.3 Phase 1 Arkhe 基础设施
09a5a02  §B.2 typed Modifier list + DamageModifierLog 栈
ebb50c1  §B.0 modifier 频次实证统计工具
914e142  §A.2 find_char_by_kind builtin (enum-based)
7f52ec8  §B.1 Element.Piercing 替代 Penetrate flag
c8fcb6a  §A.1 启用 ctx.is_specialty
ce2a60a  ADR-0019 docs PROPOSED
56d45d8  gitignore add ref/
```

## 当前已 ship(全 strict,0 fallback)

### 引擎语义层
- **strict 8 hook 时机** damage 流水线:
  ```
  HookDamageType → HookDamageAdd → HookDamageMul → HookReactionDamage →
  HookDamageReduceBuff → HookShieldAbsorb → HookDamageImmunity → 扣血 →
  HookAfterDamage
  ```
  旧 `HookDamageBoost` / `HookDamageReduce` **fire 已删**(enum 仍存避免 hook map 重排,但永不触发)
- **`Element.Piercing`** typed enum,删 Penetrate flag + 所有 backward-compat
- **`ctx.absorbed`** field (reduce 阶段后 set,以逸待劳类反击 idiom 用)
- **`ctx.reaction_kind`** typed ID(DSL declare_reaction 注册得 ID)
- **`ctx.is_specialty`** 启用
- **`Game.RecentDamageEvents`** ring(K=8,typed snapshot)
- **`Game.DamageModifierLog`** 栈(per-call,带 element 维度)
- **`Game.ReactionRegistry`**(name → ID,支持 DSL 新增反应)
- **`Game.skillIdentityMap`** via `Runtime.SkillIdentityOf`(P0-γ:obs prepare-skill 反查 typed pair 不暴露 global skillID)
- **obs schema +92 slots**:88 recent_damage(K=8 × 11 fields)+ 4 prepare-skill

### DSL 表达力
- **13 处 v_legacy lua 已 strict migrate**(铁枪/西风剑/佛跳墙/蝶火/刻印/结晶/荷花酥/天星岩脊/墨意/猫爪护盾/以逸待劳/测试卡_增幅/declare_shield)
- **`find_char_by_kind(player, Kind)`** 5 Kind enum(LowestHp/HighestHp/LeastDamaged/RandomNonActive/PreviousActive)
- **`declare_shield(name, scope, count, opts)`** macro(builtin,注册 HookShieldAbsorb)
- **`declare_reaction("X")` + `set_reaction_kind(R)`**(8 reactions 已用)
- **`Arkhe` enum**(None/Pneuma/Ousia)+ `_arche_marker` global counter(Phase 1 基础设施)

### 工具
- `tools/scan_modifier_frequency.py`:706 yaml 静态扫,P95=5/P99=14/MAX=17 → K_mod=16

### 测试
- 11 spike test 全 PASS(specialty / piercing / find_char / arche_lib / arche_mechanism / damage_modifier / reaction_kind / recent_damage / declare_shield / obs_encoder_b3c / strict_hook_b5)
- 全 suite (`./gicg_engine/{,interp,tests,v2}/ -count=1`)PASS,0 regression

## 已完成 (本次 session 2026-05-07)

### Phase 2 per-card 4 char lua + Tune hook (~700 LOC)
- ✅ 克洛琳德 (Pneuma marker, 4 file + simplified 夜巡/生命之契 status)
- ✅ 攻坚特化型机关·荒 (Ousia 能源特征 + 失能形态 + 始基反应闭环, 4 file)
- ✅ 陆行岩本真蕈 (陆地优势/枯焦/活化 状态机, 4 file)
- ✅ 水史莱姆 (元素生命·水: 总附着 + 水免疫, 3 file)
- ✅ §A.4 Tune hook (HookOnTune + DSL on_tune,3-5 张卡可用)

### §B.5 enum 清理
- ✅ HookDamageBoost / HookDamageReduce enum 完全删除
- 旧 token (TokOnDamageBoost=80, TokOnDamageReduce=82) reserved 不复用

## 留下次 session (out-of-ADR-scope)

### dylib 重建 + Python pytest 验证 (本 session 环境阻塞)

cgo 在本 session 因 Xcode license 阻塞 (sudo xcodebuild -license 需
交互),Python 端 obs unpack 改动只验证了 source 正确性,end-to-end
pytest 待 dylib 重建后跑:

```bash
sudo xcodebuild -license  # one-time
go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/
.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q
```

旧 dylib (§B.3a 之前) 当前 fail because declare_reaction 等 builtin
缺失;重建后应 PASS (engine + Python schema 已同步)。

### BC dataset regen (RL ops session)

DynamicObsSize 从 §B.3a 之前的 ~2157 涨到现在的 ~2409 (+92 §B.3c +
160 §B.2 modifier_log = +252 typed slots)。所有 §B.3a 之前的 BC ckpt
+ replay buffer 失效需重新生成。**不在 ADR-0019 范围。**

### 网络层消费 typed segments (future training PR)

当前 Python obs unpack 只 expose typed segments (recent_damage /
prepare_skill / modifier_log) 给 step_encoding.parse_dynamic_typed_np,
但 agent_base._parse_dynamic_single 仍只 pack 4 tensors (meta /
counter / card / enemy_sizes) 给网络。Future training PR:
- agent_base 增加 typed embedders (Element / ReactionKind / ModifierKind)
- recent_damage / modifier_log per-event sequence 走 attention 或 conv
- prepare_skill 走 typed embedding lookup
不阻塞当前训练 (typed segments 不用就被忽略)。

## Phase 2 简化清单 (本 session 不做 — 高 fidelity 完整实施留 future)

- 克洛琳德 cancelHealed hook (治疗→生命之契 转换):需新 hook 时机
- 克洛琳德 deductVoidCost (夜巡内普攻少 1 无色):需 cost mod hook
- 攻坚机关·荒 战技 准备技能 (盾刃切割 准备 1 行动轮):用 set_preparing 但未做
- 攻坚机关·荒 失能形态 切换技能集 (失能形态版近距格斗等):需 alt skill set 表达
- 陆行岩 状态切换 切换 元素附着 / 阻断反应:需更细的 buff effect

## 测试覆盖
- 4 个新 spike test,共 11 case PASS:
  - TestClorindeBasicSpike (4 case)
  - TestClockworkOusiaSpike (3 case, 含始基反应闭环 + 同性不触发)
  - TestPyrohelminthSpike (4 case, 状态机切换 + 永久切换)
  - TestWaterSlimeSpike (2 case, 水免疫 + 火伤正常)
  - TestTuneHookSpike (2 case, Go-side + DSL-side fire 验证)
- 全 ./gicg_engine/{tests,interp}/ -count=1 PASS, 0 regression

## 关键技术约束(影响 future 设计)

1. **lua DSL 不支持 closure return value**:`ReturnStmt struct{}` 无 value 字段;callClosure 不传 return。所有 builtin 接 lambda 路线**必证伪**,改 enum-based。
2. **lua DSL 不支持顶层 `function name(...) end` 声明 + 顶层全局表赋值**:`Arkhe = {...}` 这种顶层赋值会 parse error。所有"全局 namespace"必须 engine 注入(类比 Element/Tag/Scope)或 declare-pattern
3. **对照实现**:`ref/genius-invokation/`(AGPLv3,完整卡池)— 反应表 typed ReactionMap / 护盾 entity-bound hook builder 模式;clone 后用作架构对照 + 后续对拍 source

## 关键路径

- ADR:`docs/2_decisions/adr-0019-dsl_v6_semantic_engine.md`
- 进度:本文档
- DSL gaps:`docs/3_plans/cards/dsl_gaps.md`
- 对照:`ref/genius-invokation/`(.gitignore,40MB)
- v4 prototype 存档:`gicg_engine/v2/`(3705 LOC,25 test PASS,不上线)
