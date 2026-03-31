# 完整角色测试覆盖

## 测试原则

> **每个角色的每个技能、被动、天赋、召唤物效果都必须有独立测试。**

```
角色测试清单:
□ 普通攻击 (Normal Attack)
□ 元素战技 (Elemental Skill)  
□ 元素爆发 (Elemental Burst)
□ 被动技能 (Passive) - 如果有
□ 天赋牌效果 (Talent Card) - 如果有
□ 召唤物效果 (Summon) - 如果有
□ 特殊机制 (Special) - 如元素转换、护盾等
```

## 1. 菲谢尔完整测试

### 1.1 普通攻击 - 罪灭之矢

```go
func TestFischlNormalAttack(t *testing.T) {
    world := setupScenario("fischl", "dummy")
    enemy := world.GetEnemyActive()
    
    // 使用普攻
    world.ExecuteSkill("fischl_normal_attack")
    
    // 验证：2点物理伤害
    assert.Equal(t, 8, enemy.HP)  // 10 - 2 = 8
    assert.Equal(t, PHYSICAL, world.GetLastDamageElement())
}
```

### 1.2 元素战技 - 夜巡影翼

```go
func TestFischlElementalSkill(t *testing.T) {
    world := setupScenario("fischl", "dummy")
    enemy := world.GetEnemyActive()
    
    // 使用E技能
    world.ExecuteSkill("fischl_e")
    
    // 验证：立即造成1点雷伤
    assert.Equal(t, 9, enemy.HP)
    assert.Equal(t, ELECTRO, world.GetLastDamageElement())
    
    // 验证：奥兹Counter = 2
    assert.Equal(t, 2, world.GetCounter("fischl_oz_uses"))
    
    // 回合结束，奥兹触发
    world.EndPhase()
    
    // 验证：1点雷伤，Counter = 1
    assert.Equal(t, 8, enemy.HP)
    assert.Equal(t, 1, world.GetCounter("fischl_oz_uses"))
    
    // 再一轮，Counter = 0，奥兹消失
    world.EndPhase()
    assert.Equal(t, 7, enemy.HP)
    assert.Equal(t, 0, world.GetCounter("fischl_oz_uses"))
    
    // 再一轮，不应触发
    world.EndPhase()
    assert.Equal(t, 7, enemy.HP)  // HP不变
}
```

### 1.3 元素爆发 - 至夜幻现

```go
func TestFischlElementalBurst(t *testing.T) {
    world := setupScenario("fischl", "triple_dummy")
    enemies := world.GetEnemyCharacters()
    
    // 前台HP=10, 后台1HP=10, 后台2HP=10
    
    // 使用大招 (需要3能量)
    world.SetEnergy(0, 3)  // 给菲谢尔3能量
    world.ExecuteSkill("fischl_burst")
    
    // 验证：前台受到4点雷伤
    assert.Equal(t, 6, enemies[0].HP)
    
    // 验证：后台各受到2点穿透伤害
    assert.Equal(t, 8, enemies[1].HP)
    assert.Equal(t, 8, enemies[2].HP)
    
    // 验证：召唤奥兹 (Counter=2)
    assert.Equal(t, 2, world.GetCounter("fischl_oz_uses"))
}
```

### 1.4 被动技能 - 夜巡影翼 (战斗开始时)

```go
func TestFischlPassive(t *testing.T) {
    world := setupScenario("fischl", "dummy")
    
    // 战斗开始时自动触发被动
    world.StartBattle()
    
    // 验证：场上存在奥兹 (如果有被动版奥兹)
    // 或验证其他被动效果
}
```

### 1.5 天赋牌 - 噬星魔鸦

```go
func TestFischlTalentCard(t *testing.T) {
    world := setupScenario("fischl", "dummy")
    
    // 装备天赋牌
    world.EquipTalentCard("fischl_talent")
    
    // 使用E技能
    world.ExecuteSkill("fischl_e")
    
    // 验证：天赋效果 - 雷元素反应伤害+1
    // 需要敌方有元素附着
    world.AttachElementToEnemy(HYDRO)
    world.EndPhase()  // 触发奥兹
    
    // 感电反应伤害应为2 (1基础+1天赋)
    assert.Equal(t, 2, world.GetLastReactionDamage())
}
```

## 2. 迪卢克完整测试

### 2.1 普通攻击 - 淬炼之剑

```go
func TestDilucNormalAttack(t *testing.T) {
    world := setupScenario("diluc", "dummy")
    
    world.ExecuteSkill("diluc_normal_attack")
    
    // 2点物理伤害
    assert.Equal(t, 8, world.GetEnemyHP())
    assert.Equal(t, PHYSICAL, world.GetLastDamageElement())
}
```

### 2.2 元素战技 - 逆焰之刃 (3段)

```go
func TestDilucElementalSkillCombo(t *testing.T) {
    world := setupScenario("diluc", "dummy")
    
    // 连续使用6次E技能
    damages := []int{}
    for i := 0; i < 6; i++ {
        hpBefore := world.GetEnemyHP()
        world.ExecuteSkill("diluc_e")
        damages = append(damages, hpBefore-world.GetEnemyHP())
    }
    
    // 验证伤害序列 [3,3,5,3,3,5]
    assert.Equal(t, []int{3, 3, 5, 3, 3, 5}, damages)
    
    // 验证元素都是火
    for i := 0; i < 6; i++ {
        assert.Equal(t, PYRO, world.GetDamageHistory()[i].Element)
    }
}
```

### 2.3 元素爆发 - 黎明

```go
func TestDilucElementalBurst(t *testing.T) {
    world := setupScenario("diluc", "dummy")
    enemy := world.GetEnemyActive()
    
    // 使用大招
    world.SetEnergy(0, 3)
    world.ExecuteSkill("diluc_burst")
    
    // 验证：8点火伤
    assert.Equal(t, 2, enemy.HP)  // 10 - 8 = 2
    assert.Equal(t, PYRO, world.GetLastDamageElement())
    
    // 验证：获得火元素附魔 Mod
    assert.True(t, world.HasMod(0, "diluc_pyro_infusion"))
    
    // 验证：附魔持续2回合
    world.ExecuteSkill("diluc_normal_attack")
    assert.Equal(t, PYRO, world.GetLastDamageElement())  // 普攻变火伤
    
    world.EndRound()
    world.EndRound()  // 2回合后
    
    world.ExecuteSkill("diluc_normal_attack")
    assert.Equal(t, PHYSICAL, world.GetLastDamageElement())  // 恢复物理
}
```

### 2.4 天赋牌 - 流火焦灼

```go
func TestDilucTalentCard(t *testing.T) {
    world := setupScenario("diluc", "dummy")
    
    world.EquipTalentCard("diluc_talent")
    
    // 第3段E技能伤害+1
    world.ExecuteSkill("diluc_e")  // 第1段，3伤
    world.ExecuteSkill("diluc_e")  // 第2段，3伤
    
    hpBefore := world.GetEnemyHP()
    world.ExecuteSkill("diluc_e")  // 第3段，应为6伤(5+1)
    assert.Equal(t, 6, hpBefore-world.GetEnemyHP())
}
```

## 3. 阿蕾奇诺完整测试

### 3.1 普通攻击 - 斩首之邀

```go
func TestArlecchinoNormalAttack(t *testing.T) {
    world := setupScenario("arlecchino", "dummy")
    
    // 测试1: 无生命之契，无血偿勒令
    world.ExecuteSkill("arlecchino_attack")
    assert.Equal(t, 8, world.GetEnemyHP())  // 2物理伤
    assert.Equal(t, PHYSICAL, world.GetLastDamageElement())
    
    // 测试2: 有血偿勒令，增伤
    world.Reset()
    world.SetTargetCounter(1, "blood_debt", 3)  // 敌方3层血债
    
    world.ExecuteSkill("arlecchino_attack")
    assert.Equal(t, 5, world.GetEnemyHP())  // 2+3=5伤
    assert.Equal(t, 0, world.GetTargetCounter(1, "blood_debt"))  // 消耗完
    
    // 测试3: 有生命之契，元素转换
    world.Reset()
    world.SetCounter(0, "arlecchino_life_debt", 2)  // 自己2层
    
    world.ExecuteSkill("arlecchino_attack")
    assert.Equal(t, PYRO, world.GetLastDamageElement())  // 转为火伤
}
```

### 3.2 元素战技 - 万相化灰

```go
func TestArlecchinoElementalSkill(t *testing.T) {
    world := setupScenario("arlecchino", "triple_dummy")
    enemies := world.GetEnemyCharacters()
    
    // 使用E技能
    world.ExecuteSkill("arlecchino_e")
    
    // 验证：对每个敌方造成2点火伤
    for _, e := range enemies {
        assert.Equal(t, 8, e.HP)
    }
    
    // 验证：给敌方添加血偿勒令 (如果E技能有这个效果)
    // 或验证其他E技能效果
}
```

### 3.3 元素爆发 - 厄月将升

```go
func TestArlecchinoElementalBurst(t *testing.T) {
    world := setupScenario("arlecchino", "dummy")
    
    // 先给自己加生命之契
    world.SetCounter(0, "arlecchino_life_debt", 3)
    
    hpBefore := world.GetHP(0)
    
    // 使用大招
    world.SetEnergy(0, 3)
    world.ExecuteSkill("arlecchino_burst")
    
    // 验证：4点火伤
    assert.Equal(t, 6, world.GetEnemyHP())
    
    // 验证：消耗所有生命之契，治疗自己
    assert.Equal(t, 0, world.GetCounter(0, "arlecchino_life_debt"))
    assert.Equal(t, hpBefore+3, world.GetHP(0))  // 治疗3点
}
```

### 3.4 被动技能 - 唯厄月可知晓

```go
func TestArlecchinoPassiveBattleStart(t *testing.T) {
    world := setupScenario("arlecchino", "triple_dummy")
    enemies := world.GetEnemyCharacters()
    
    // 战斗开始
    world.StartBattle()
    
    // 验证：所有敌方获得3层血偿勒令
    for _, e := range enemies {
        assert.Equal(t, 3, world.GetTargetCounter(e, "blood_debt"))
    }
}

func TestArlecchinoPassiveInfusion(t *testing.T) {
    world := setupScenario("arlecchino", "dummy")
    
    // 有生命之契时
    world.SetCounter(0, "arlecchino_life_debt", 1)
    world.ExecuteSkill("arlecchino_attack")
    assert.Equal(t, PYRO, world.GetLastDamageElement())
    
    // 无生命之契时
    world.SetCounter(0, "arlecchino_life_debt", 0)
    world.ExecuteSkill("arlecchino_attack")
    assert.Equal(t, PHYSICAL, world.GetLastDamageElement())
}

func TestArlecchinoPassiveHealBlock(t *testing.T) {
    world := setupScenario("arlecchino", "dummy")
    
    // 其他角色尝试治疗阿蕾奇诺 (被阻止)
    hpBefore := world.GetHP(0)
    world.HealFromOtherCharacter(0, 5)
    assert.Equal(t, hpBefore, world.GetHP(0))  // 治疗被阻止
    
    // 自己大招治疗 (允许)
    world.SetCounter(0, "arlecchino_life_debt", 3)
    world.SetEnergy(0, 3)
    world.ExecuteSkill("arlecchino_burst")
    assert.True(t, world.GetHP(0) > hpBefore)  // 治疗成功
}
```

### 3.5 天赋牌 - 所有的仇与债皆由我偿

```go
func TestArlecchinoTalentCard(t *testing.T) {
    world := setupScenario("arlecchino", "dummy")
    
    world.EquipTalentCard("arlecchino_talent")
    
    // 给阿蕾奇诺3层生命之契
    world.SetCounter(0, "arlecchino_life_debt", 3)
    
    // 受到5点伤害
    world.DealDamageTo(0, 5)
    
    // 天赋效果：消耗1层抵消1点伤害
    assert.Equal(t, 2, world.GetCounter(0, "arlecchino_life_debt"))  // 剩2层
    assert.Equal(t, 8, world.GetHP(0))  // 实际受到4点伤害 (5-1)
}
```

## 4. 测试自动化

### 4.1 角色测试套件

```go
// character_test_suite.go

type CharacterTestSuite struct {
    Name     string
    Tests    []SkillTest
}

type SkillTest struct {
    Name        string
    SkillID     string
    Setup       func(*World)
    Execute     func(*World)
    Expectations []Expectation
}

type Expectation struct {
    Type   string  // "hp", "counter", "element", "mod", etc.
    Target int     // 0=self, 1=enemy
    Value  interface{}
}

// 注册所有角色测试
var AllCharacterTests = []CharacterTestSuite{
    FischlTestSuite,
    DilucTestSuite,
    ArlecchinoTestSuite,
    GanyuTestSuite,
    // ... more
}

func RunAllCharacterTests(t *testing.T) {
    for _, suite := range AllCharacterTests {
        t.Run(suite.Name, func(t *testing.T) {
            for _, test := range suite.Tests {
                t.Run(test.Name, func(t *testing.T) {
                    world := setupTestWorld()
                    test.Setup(world)
                    test.Execute(world)
                    
                    for _, exp := range test.Expectations {
                        verifyExpectation(t, world, exp)
                    }
                })
            }
        })
    }
}
```

### 4.2 CI 测试脚本

```bash
#!/bin/bash
# test_characters.sh

echo "=== 菲谢尔全技能测试 ==="
go test -v -run "TestFischl"

echo "=== 迪卢克全技能测试 ==="
go test -v -run "TestDiluc"

echo "=== 阿蕾奇诺全技能测试 ==="
go test -v -run "TestArlecchino"

echo "=== 甘雨全技能测试 ==="
go test -v -run "TestGanyu"

echo "=== 全部角色测试完成 ==="
```

## 5. 测试覆盖率检查

```bash
# 生成覆盖率报告
go test -coverprofile=coverage.out ./...
go tool cover -func=coverage.out

# 期望：每个角色的每个技能都有独立测试函数
# 检查：角色数 × 平均技能数 ≈ 测试函数数
```

---

**核心原则**: 没有任何一个技能效果被遗漏测试。
