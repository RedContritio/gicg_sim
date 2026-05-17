> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **IMPLEMENTED 2026-05-15**
> - 实施 commit 链:7891481(plan)→ c02bc88(事件 3 卡 e2e)→ 10ce0c9(支援 2 卡 e2e + 派蒙 lifecycle + 鸣神大社)→ 2fca63b(装备 2 卡 e2e + weapon mismatch)
> - 7 e2e test cases ship,cleaned yaml ground truth 断言

---

# v_phase2 卡 e2e 测试实现计划

> 2026-05-15 落盘。
>
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans / subagent-driven-development。Step 用 `- [ ]` checkbox。
>
> 上下文:`TestVPhase2CardFieldLocks` 仅锁定卡声明字段(cost / slot / requires_weapon)。卡的 **真实运行时效果** 未被测试覆盖 — 如旅行剑/魔导绪论"角色造成伤害+1"、派蒙"行动阶段开始时生成 2 Omni × 可用次数 2"、鸣神大社"使用技能后骰子奇数则 +1 Omni / 每回合 2 次"。本计划补 e2e 测试覆盖每卡运行时效果。

**Goal:** 走 production `GetLegalActions / Step` 真路径,A/B 对比每张 v_phase2 卡的真实效果。断言数值**从 `data/cleaned/action/*.yaml` ground truth** 抽,不读 lua 实现(test 与 lua 同源 = 锁死 bug)。

**Architecture:** 3 个 test 文件分子类(事件 / 支援 / 装备),每张卡 happy A/B 对比 + 必要 negative case。无新 helper(`helpers_test.go` 现有 `StepSkill / StepEndTurn / SetDice / FindAction / HP / DiceTotal` + `charEntry.NormalAttackID` 已足够)。Round 推进用 `env.StepEndTurn() × 2`(engine 自动 RoundEnd → RoundStart,无需手写 helper)。

**Tech Stack:** Go testing + 现有 e2e helper(`tests/helpers_test.go`)

---

## 审计已确认(动手前不需再 grep)

### Ground truth 抓取自 `data/cleaned/action/<id>_<name>.yaml`

| 卡 | yaml id | `effect_text`(原文) | Δ 断言 ground truth |
|---|---|---|---|
| 旅行剑 | 5418 | **"角色造成的伤害+1。(「单手剑」角色才能装备。角色最多装备1件「武器」)"** | 装备者**任意伤害源** +1(不限 normal attack) |
| 魔导绪论 | 5406 | **"角色造成的伤害+1。(「法器」角色才能装备。…)"** | 同上,装备者「法器」 |
| 甜甜花酿鸡 | 5475 | **"治疗目标角色 1 点。"** | target HP +1 + 饱腹=1 |
| 蒙德土豆饼 | 5529 | **"治疗目标角色 2 点。"** | target HP +2 + 饱腹=1 |
| 最好的伙伴！ | 5480 | **"生成 2 个万能元素。"** | dice_omni +2 |
| 派蒙 | 5448 | **"行动阶段开始时:生成 2 点万能元素... 可用次数:2"** | 2 个真 round_start 各 +2 Omni,然后退槽 → Discard |
| 鸣神大社 | 6325 | **"我方角色使用技能后:如果元素骰总数为奇数,则生成 1 个万能元素(每回合 2 次)"** | 3 条件:技能后 × 骰子总数奇数 × 每回合 ≤2 次 |

### v_phase2 char 武器类型(已 grep)

- 凯亚 = **Sword**(`v_legacy` 武器枚举 1)→ 装旅行剑
- 凝光 = **Catalyst**(枚举 5)→ 装魔导绪论
- 其他 v_phase2 char 武器类型 implement 时按需 grep

### Helper 现状(`helpers_test.go`)

足够,**无新 helper**:
- `env.SetDice(p, {color: n})` — 强制 dice 池
- `env.HP(p, c)` / `env.DiceTotal(p)` / `env.Alive(p, c)` — 读 state
- `env.FindAction(kind, name)` — 按名 lookup legal action index
- `env.Step(idx)` — execute + auto-target(取 idx 0)
- `env.StepSkill(name)` / `env.StepEndTurn()` — 命名 skill / EndTurn
- `env.RT.Cards.ByName[name]` → `*CardRef`
- `env.RT.Chars.BySlot[p][c].NormalAttackID` → 拿 normal attack skill ID

### Round 推进(双方 EndTurn → engine 自动进新 round)

`gicg_engine/round.go:9`(`enterRoundPause` setting Phase=PhaseRoundStart)和现有 `record_test.go` / `clone_test.go` 用 `env.StepEndTurn()` 推进确认:双方都 `EndTurn` 后,engine 自动跑完 RoundEnd → RoundStart → fresh PhaseAction,**无需手写 AdvanceOneRound helper**。

### 召唤物 / 手牌伤害源反面 defer 理由

- v_phase2 7 张卡 + 7 个 char 内**无召唤物声明**(`grep -rl declare_summon data/pools/v_phase2/` 无结果)
- v_legacy 召唤物 char(猫咪=Bow / 天星=Polearm)武器类型与 v_phase2 装备牌(Sword/Catalyst)**不匹配**
- 手牌伤害事件牌 v_phase2 没有(只有 0 伤害的事件 + heal + dice 卡)
- **可行替代反面**:用同侧**非装备角色**(P0 char 0 装旅行剑,P0 char 1 用技能 → +1 不该 leak)

---

## File Structure

```
gicg_engine/tests/
├── v_phase2_event_cards_e2e_test.go    新文件 ~280 LOC
├── v_phase2_support_cards_e2e_test.go  新文件 ~290 LOC
└── v_phase2_equip_cards_e2e_test.go    新文件 ~280 LOC
```

无修改现有文件。

---

## Task 1: 事件卡 e2e(3 happy + 2 negative)

**File:** `gicg_engine/tests/v_phase2_event_cards_e2e_test.go`(新)

### Test 列表

1. **`TestEvent_甜甜花酿鸡_HealOwn1`** — 出卡 target self → assert HP +1 + 饱腹=1 + 卡进 Discard。A=不出 baseline HP delta=0;B=出 delta=+1
2. **`TestEvent_甜甜花酿鸡_BlockedWhenFull`** — negative:饱腹=1 时 `FindAction` 返 -1
3. **`TestEvent_蒙德土豆饼_HealOwn2`** — 同 happy,cost match=1,Δ +2
4. **`TestEvent_蒙德土豆饼_BlockedWhenFull`** — negative
5. **`TestEvent_最好的伙伴_GenOmni2`** — A=不出 dice_omni=0;B=付 2 fire 出 → dice_omni=2 + dice_fire=0 + 卡进 Discard

### Setup pattern(每 test 复用)

```go
env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
// NewGameWithDeck 已推进到 PhaseAction
card := env.RT.Cards.ByName["甜甜花酿鸡"]
env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})

// 给 P0 char 0 受 1 伤(测 heal)
env.G.Counters[env.RT.Chars.BySlot[0][0].HPCounterID].Value = 9 // max=10, set=9

// happy A baseline: 跳过一回合不出卡
hpBefore := env.HP(0, 0)
// (no card play)
hpAfterA := env.HP(0, 0)  // == 9, delta=0

// happy B with card: 出卡 target self
idx := env.FindAction(engine.ActionCard, "甜甜花酿鸡")
if idx < 0 { t.Fatalf("card not offered") }
env.Step(idx)  // auto-target 0(自身)
hpAfterB := env.HP(0, 0)
if hpAfterB - hpBefore != 1 {
    t.Errorf("HP delta = %d, want +1 (cleaned 5475: 治疗目标角色 1 点)", hpAfterB - hpBefore)
}
// 饱腹 / Discard 验证类似
```

### Implementation 期具体步骤(每 test 内部)

- [ ] Setup `NewGameWithDeck`
- [ ] Inject 卡到 P0 hand
- [ ] (heal 类)mock target HP < max
- [ ] (event cost > 0)`SetDice(0, ...)` 满足 cost
- [ ] `FindAction(ActionCard, name)` → 断言 idx ≥ 0
- [ ] `Step(idx)` — auto-target
- [ ] Assert post-state(HP / 饱腹 / Discard / dice)
- [ ] Negative case:condition 不满足时 `FindAction` 返 -1

### Commit

```bash
git add gicg_engine/tests/v_phase2_event_cards_e2e_test.go
git commit -m "tests: v_phase2 事件 3 卡 e2e — 真路径 + ground truth(cleaned yaml)断言"
```

---

## Task 2: 支援卡 e2e(派蒙 lifecycle + 鸣神大社 3 sub-test + 2 negative)

**File:** `gicg_engine/tests/v_phase2_support_cards_e2e_test.go`(新)

### Test 列表

1. **`TestSupport_派蒙_TwoRoundLifecycle`** — 完整 lifecycle:
   - 出派蒙(cost match=3 fire dice)→ assert Supports[0]=派蒙 + 派蒙_active=2 + dice_omni 不变
   - `env.StepEndTurn() × 2` 推进到 round 2 → assert dice_omni +2(round_start fire) + active=1 + Supports 仍有
   - 再 `StepEndTurn() × 2` 推进到 round 3 → assert dice_omni 又 +2(累计 +4)+ active=0 + Supports 空 + Discard 含派蒙

2. **`TestSupport_派蒙_BlockedWhenFull`** — Supports 满 4 槽位 → `FindAction` 返 -1

3. **`TestSupport_鸣神大社`**(`t.Run` 3 sub-test):
   - **happy:** 出大社 + 用任意技能 + setDice 凑奇数总数 → assert dice_omni +1
   - **condition:** 出大社 + 用技能 + setDice 凑偶数 → assert dice_omni 不变(condition 不满足)
   - **limit:** 出大社 + 用 3 次技能(均奇数 dice)→ 第 3 次 dice_omni 不再 +1(每回合 ≤2 次)

4. **`TestSupport_鸣神大社_BlockedWhenFull`** — Supports 满 → `FindAction` 返 -1

### Setup 关键

- 派蒙 cost match=3:`SetDice(0, {fire: 3})` 然后 enumerate(GICG match 在 dice payment 时寻同色 3 个)
- 鸣神大社 cost match=2:`SetDice(0, {fire: 2})` 然后还要凑技能 cost — implement 期决定具体 dice setup
- 鸣神大社"骰子总数奇数":总 dice = 1 / 3 / 5 / 7 = 奇数;= 2 / 4 / 6 / 8 = 偶数。Setup 用 `SetDice` 精确控制 total。

### Commit

```bash
git add gicg_engine/tests/v_phase2_support_cards_e2e_test.go
git commit -m "tests: v_phase2 支援 2 卡 e2e — 派蒙 lifecycle + 鸣神大社 3 条件 sub-test"
```

---

## Task 3: 装备卡 e2e(2 happy 各 ≥2 skill type + 2 negative + 1 同侧非装备 char 反面)

**File:** `gicg_engine/tests/v_phase2_equip_cards_e2e_test.go`(新)

### Test 列表

1. **`TestEquip_旅行剑_AnyDamageSource`**(凯亚=Sword,≥2 skill type):
   - A baseline:凯亚不装旅行剑,用 normal attack → enemy HP delta D₁ₐ
   - B with equip:凯亚装旅行剑 + 同 normal attack → delta D₁ᵦ。**Assert D₁ᵦ - D₁ₐ = +1**
   - 用 element skill(凯亚战技 / 爆发)重复 A/B → **Assert delta = +1**(验证 yaml "角色造成伤害+1"不限 normal attack)

2. **`TestEquip_旅行剑_NotLeakToTeammate`**(同侧非装备角色反面):
   - P0 = [凯亚, 凝光]
   - 凯亚 装旅行剑(Sword 满足)
   - 凝光(Catalyst,**未装** anything)用技能 → assert delta = baseline(凝光伤害**不** +1 — 装备只 buff 装备者)

3. **`TestEquip_旅行剑_BlockedNonSword`** — negative:active char weapon ≠ Sword(用凝光 Catalyst)→ `FindAction("旅行剑")` 返 -1

4. **`TestEquip_魔导绪论_AnyDamageSource`** — 同 1,凝光 Catalyst,≥2 skill type

5. **`TestEquip_魔导绪论_BlockedNonCatalyst`** — negative:凯亚 Sword → -1

### 装备机制查证(implement 期必做)

- 装备牌 effect 实现方式 implement 期读 lua + engine `charEntry` 字段确认:
  - 是否有 `charEntry.EquippedWeapons []CardRef`?(类似 `SpecialtyCardRef`)
  - 还是用 counter `weapon_equip_<charSlot>` mark + DSL `on_damage_add` hook 加 +1?
- Test 不依赖 lua 实现细节,只 assert"装备后 damage +1"行为

### Skill type 覆盖

每张装备牌测 ≥2 skill type(普攻 + 元素战技/爆发),确认 yaml "**任意**伤害源 +1"不限 normal attack:
- 凯亚:`SkillID("凯亚", "<normal attack name>")` + `SkillID("凯亚", "<element skill name>")`
- 凝光:同
- 具体 skill 名 implement 期查 char declare(看 `v_phase2/characters/<name>/<name>.lua`)

### Commit

```bash
git add gicg_engine/tests/v_phase2_equip_cards_e2e_test.go
git commit -m "tests: v_phase2 装备 2 卡 e2e — A/B damage delta + 非装备 char 反面 + weapon mismatch negative"
```

---

## Risks / 未覆盖(已 acknowledge)

1. **召唤物伤害源反面 defer** — v_phase2 无召唤物 char + v_legacy 召唤物 char 武器类型不匹配 v_phase2 装备牌。Future:v_phase2 加召唤物 char 或扩展装备牌支持 Bow/Polearm 后补
2. **手牌伤害源反面 defer** — v_phase2 无 damage 事件牌
3. **装备 effect lua 实现细节未知** — implement 期看 lua 实际机制(counter+hook 还是 charEntry 字段),test assert 不依赖,只看 damage delta
4. **鸣神大社 dice setup 复杂** — 总骰数奇偶判定需精确 SetDice,具体 dice setup implement 期决定

---

## 不在 scope

- v_phase2 char 自身技能 e2e(angular separate scope,见 `v_phase2_chars_field_lock_test.go` 字段锁定即可)
- v_phase2 之外 pool 的卡 e2e
- Python obs encoder 暴露装备/支援区
- 装备牌的 talent buff 机制(目前 v_phase2 装备牌无 talent)

---

## Self-review

- [x] Ground truth 全部来自 cleaned yaml,引用 yaml id 标注,不读 lua
- [x] A/B 对比每卡 effect,不接受"hook fired / 槽位被占"作 evidence
- [x] Round 推进用 `StepEndTurn × 2`(无新 helper)
- [x] 装备 reverse case 改"同侧非装备 char",召唤物 / 手牌 defer 明示理由
- [x] 3 文件各 < 300 行 Go hook limit(估算 280/290/280)
- [x] 3 commits 独立 commit-ready
- [x] Implement 期未知项明示(装备 lua 实现细节 / 鸣神大社 dice setup 细节)
