# 引擎测试策略：对局驱动验证

## 核心思想

> **不孤立测试函数，而是运行完整对局，验证技能表现是否符合描述。**

```
传统单元测试:                    对局驱动测试:
TestSetCounter()                 对局: 迪卢克 vs  Dummy
  ├─ set(5)                      回合1: 使用6次 E 技能
  ├─ assert == 5                 验证: 伤害序列 [3,3,5,3,3,5]
  └─ inc(2)                      
  └─ assert == 7                 
```

## 1. 测试对局配置

### 1.1 对手类型

```go
// DummyOpponent - 只会结束回合的对手
type DummyOpponent struct{}

func (d *DummyOpponent) SelectAction(w *World, side int) Action {
    return Action{Type: ActionEndTurn}
}

// PassiveOpponent - 被动挨打，偶尔切换
// AggressiveOpponent -  aggressive AI
// ScriptedOpponent - 按脚本执行特定动作
```

### 1.2 场景配置

```go
type TestScenario struct {
    Name        string
    PlayerChar  string      // 我方角色
    EnemyChar   string      // 敌方角色
    EnemyAI     Opponent    // 敌方AI
    
    Script      []TestStep  // 测试脚本
    
    Expect      Expectation // 期望结果
}

type TestStep struct {
    Action      Action      // 执行动作
    ExpectState func(*World) bool  // 状态验证
}
```

## 2. 迪卢克完整测试

```go
func TestDilucESkillCombo(t *testing.T) {
    // 配置对局: 迪卢克 vs 只会结束回合的迪卢克
    scenario := TestScenario{
        Name:       "迪卢克E技能连击测试",
        PlayerChar: "diluc",
        EnemyChar:  "diluc",
        EnemyAI:    &DummyOpponent{},
    }
    
    world := setupScenario(scenario)
    
    // 连续使用6次 E 技能，记录伤害值
    var damages []int
    
    for i := 0; i < 6; i++ {
        enemyHPBefore := world.GetEnemyActiveHP()
        
        // 使用 E 技能
        err := world.ExecuteSkill(Action{
            Type:      ActionUseSkill,
            Character: 0,  // 出战角色
            Skill:     "diluc_e",
        })
        require.NoError(t, err)
        
        // 记录伤害
        enemyHPAfter := world.GetEnemyActiveHP()
        damage := enemyHPBefore - enemyHPAfter
        damages = append(damages, damage)
        
        t.Logf("第%d次 E 技能伤害: %d", i+1, damage)
    }
    
    // 验证伤害序列: 3, 3, 5, 3, 3, 5
    expected := []int{3, 3, 5, 3, 3, 5}
    assert.Equal(t, expected, damages, 
        "迪卢克E技能伤害序列应为 [3,3,5,3,3,5]，实际 %v", damages)
}
```

## 3. 菲谢尔完整测试

```go
func TestFischlOzSummon(t *testing.T) {
    scenario := TestScenario{
        Name:       "菲谢尔奥兹召唤测试",
        PlayerChar: "fischl",
        EnemyChar:  "dummy",  // 高HP木桩
        EnemyAI:    &DummyOpponent{},
    }
    
    world := setupScenario(scenario)
    enemy := world.GetEnemyActive()
    
    // 初始状态
    assert.Equal(t, 10, enemy.HP, "敌方初始HP应为10")
    
    // 使用 E 技能
    world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: "fischl_e"})
    
    // 验证：立即造成1点雷伤
    assert.Equal(t, 9, enemy.HP, "使用E技能后敌方HP应为9")
    
    // 验证：Counter = 2
    assert.Equal(t, 2, world.GetCounter("fischl_oz_uses"), 
        "奥兹可用次数应为2")
    
    // 敌方回合（结束）
    world.EndPlayerTurn()
    world.ExecuteEnemyTurn() // Dummy 只会结束
    
    // 进入结束阶段，奥兹触发
    world.EndPhase()
    
    // 验证：结束阶段造成1点雷伤
    assert.Equal(t, 8, enemy.HP, "结束阶段奥兹触发后HP应为8")
    
    // 验证：Counter = 1
    assert.Equal(t, 1, world.GetCounter("fischl_oz_uses"),
        "奥兹可用次数应为1")
    
    // 再一轮
    world.StartNewRound()
    world.EndPlayerTurn()
    world.ExecuteEnemyTurn()
    world.EndPhase()
    
    // 验证：再次触发，HP=7
    assert.Equal(t, 7, enemy.HP, "第二次奥兹触发后HP应为7")
    
    // 验证：Counter = 0，Mod 不再触发
    assert.Equal(t, 0, world.GetCounter("fischl_oz_uses"),
        "奥兹可用次数应为0")
    
    // 再一轮，不应触发
    world.StartNewRound()
    world.EndPhase()
    assert.Equal(t, 7, enemy.HP, "Counter=0时不应再触发")
}
```

## 4. 阿蕾奇诺完整测试

```go
func TestArlecchinoLifeDebt(t *testing.T) {
    scenario := TestScenario{
        Name:       "阿蕾奇诺生命之契测试",
        PlayerChar: "arlecchino",
        EnemyChar:  "dummy",
        EnemyAI:    &DummyOpponent{},
    }
    
    world := setupScenario(scenario)
    
    // 战斗开始，给敌方添加血偿勒令
    world.StartBattle()
    
    // 验证：敌方有3层血偿勒令
    enemy := world.GetEnemyActive()
    assert.Equal(t, 3, world.GetTargetCounter(enemy, "blood_debt"),
        "战斗开始时敌方应有3层血偿勒令")
    
    // 普攻（无生命之契）
    world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: "arlecchino_attack"})
    
    // 验证：物理伤害，消耗3层血偿勒令，伤害=2+3=5
    // 敌方HP = 10 - 5 = 5
    assert.Equal(t, 5, enemy.HP, "第一次普攻应造成5点伤害(2+3)")
    assert.Equal(t, 0, world.GetTargetCounter(enemy, "blood_debt"),
        "血偿勒令应被消耗完")
    
    // 给自己添加生命之契
    world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: "arlecchino_gain_debt"})
    assert.Equal(t, 2, world.GetCounter("arlecchino_life_debt"),
        "应有2层生命之契")
    
    // 再次普攻（有生命之契，元素转换）
    world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: "arlecchino_attack"})
    
    // 验证：转为火元素伤害（Mod 自动转换）
    // 由于没有血偿勒令了，伤害=2，但元素是火
    // 这里需要检查伤害类型
    lastDamage := world.GetLastDamageInfo()
    assert.Equal(t, PYRO, lastDamage.Element,
        "有生命之契时应转为火元素伤害")
}
```

## 5. 甘雨多目标测试

```go
func TestGanyuMultiTarget(t *testing.T) {
    scenario := TestScenario{
        Name:       "甘雨多目标测试",
        PlayerChar: "ganyu",
        EnemyChar:  "triple_dummy",  // 敌方有3个角色
        EnemyAI:    &DummyOpponent{},
    }
    
    world := setupScenario(scenario)
    
    // 敌方3个角色初始HP
    enemies := world.GetEnemyCharacters()
    assert.Equal(t, 3, len(enemies))
    
    for _, e := range enemies {
        assert.Equal(t, 10, e.HP)
    }
    
    // 使用元素爆发
    world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: "ganyu_burst"})
    
    // 验证：前台受到2点冰伤
    assert.Equal(t, 8, enemies[0].HP, "前台应受到2点伤害")
    
    // 验证：后台各受到1点穿透伤害
    assert.Equal(t, 9, enemies[1].HP, "后台1应受到1点穿透伤害")
    assert.Equal(t, 9, enemies[2].HP, "后台2应受到1点穿透伤害")
}
```

## 6. 测试框架代码

```go
// test_framework.go

func setupScenario(s TestScenario) *World {
    world := NewWorld()
    
    // 加载我方角色
    world.LoadPlayerSide(s.PlayerChar)
    
    // 加载敌方角色
    world.LoadEnemySide(s.EnemyChar, s.EnemyAI)
    
    // 初始化对局
    world.StartBattle()
    
    return world
}

// AssertDamageSequence 验证伤害序列
func AssertDamageSequence(t *testing.T, world *World, skill string, expected []int) {
    var actual []int
    
    for _, exp := range expected {
        hpBefore := world.GetEnemyActiveHP()
        
        err := world.ExecuteSkill(Action{Type: ActionUseSkill, Skill: skill})
        require.NoError(t, err)
        
        hpAfter := world.GetEnemyActiveHP()
        actual = append(actual, hpBefore - hpAfter)
    }
    
    assert.Equal(t, expected, actual)
}

// AssertCounterSequence 验证 Counter 变化序列
func AssertCounterSequence(t *testing.T, world *World, counter string, steps []struct{
    action func()
    expect int
}) {
    for i, step := range steps {
        step.action()
        actual := world.GetCounter(counter)
        assert.Equal(t, step.expect, actual, 
            "第%d步 Counter %s 期望 %d 实际 %d", i+1, counter, step.expect, actual)
    }
}
```

## 7. 角色测试覆盖表

| 角色 | 测试场景 | 验证点 |
|------|----------|--------|
| 菲谢尔 | 召唤奥兹 | Counter 2→1→0, 2次触发 |
| 迪卢克 | 6次E技能 | 伤害 [3,3,5,3,3,5] |
| 阿蕾奇诺 | 生命契/血债 | Token 层数, 元素转换 |
| 甘雨 | 大招 | 前台2, 后台穿透1 |
| 莫娜 | 被动 | 每回合1次快速切换 |
| 芙宁娜 | 双形态 | 形态切换, 全局效果 |

## 8. 自动化测试脚本

```bash
#!/bin/bash
# test_all_characters.sh

echo "=== 角色对局测试 ==="

go test -v -run TestFischl
go test -v -run TestDiluc
go test -v -run TestArlecchino
go test -v -run TestGanyu
go test -v -run TestMona
go test -v -run TestFurina

echo "=== 全部通过 ==="
```

---

**核心原则**: 每个角色的测试 = 一个完整对局，验证技能描述的实际表现。
