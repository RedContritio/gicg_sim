# RL 特征学习方案

## 问题分析

```
传统 RL 观察 (不足):              需要的观察:
- 角色HP                          - 角色HP
- 能量                            - 能量
- 元素附着                        - 元素附着
- ...                             - ...
                                  - 【技能A会召唤】
                                  - 【技能B消耗3层token】
                                  - 【技能C治疗4点】
```

**核心问题**：RL 不知道"按这个按钮会发生什么"

## 解决方案：技能特征嵌入

### 1. 技能静态特征 (固定嵌入)

每个技能预计算一个特征向量：

```go
// SkillFeature - 技能静态特征 (16维)
type SkillFeature struct {
    // 基础信息 (4维)
    IsNormalAttack  float32 // 0/1
    IsElementalSkill float32 // 0/1
    IsElementalBurst float32 // 0/1
    IsPassive       float32 // 0/1
    
    // 伤害特征 (4维)
    DamageBase      float32 // 基础伤害值 (归一化 0-10)
    DamageElement   float32 // 元素类型编码 (0-7)
    IsPiercing      float32 // 是否穿透
    IsAOE           float32 // 是否范围伤害
    
    // 效果特征 (4维)
    HasSummon       float32 // 是否召唤
    HasHeal         float32 // 是否治疗
    HasTokenAdd     float32 // 是否添加token
    HasTokenConsume float32 // 是否消耗token
    
    // 资源特征 (4维)
    CostElement     float32 // 主要元素消耗
    CostAny         float32 // 任意骰消耗
    CostEnergy      float32 // 能量消耗
    CardDraw        float32 // 抽牌数量
}

// 预计算所有技能的特征
var SkillFeatureDB = map[string]SkillFeature{
    "fischl_skill": {
        IsElementalSkill: 1.0,
        DamageBase: 0.1,      // 1点伤害
        DamageElement: 3.0,   // 雷元素
        HasSummon: 1.0,       // 召唤奥兹
        CostElement: 3.0,     // 3雷骰
    },
    "arlecchino_attack": {
        IsNormalAttack: 1.0,
        DamageBase: 0.2,      // 2点基础
        DamageElement: 0.0,   // 物理 (可变)
        HasTokenConsume: 1.0, // 可能消耗token
        CostAny: 1.0,         // 1任意 + 2无色
    },
    // ...
}
```

### 2. 技能动态特征 (条件预览)

根据当前状态，计算技能的实际效果：

```go
// SkillPreview - 技能效果预览 (运行时计算)
type SkillPreview struct {
    SkillID string
    
    // 当前能否使用
    IsAvailable bool
    
    // 预测伤害 (考虑条件)
    PredictedDamageMin float32
    PredictedDamageMax float32
    DamageElement      Element
    
    // Token变化预览
    TokenChanges []TokenChangePreview
    
    // 召唤物预览
    SummonPreview *SummonPreview
    
    // 治疗预览
    PredictedHeal float32
    
    // 副作用 (对自己)
    SideEffects []SideEffect
}

type TokenChangePreview struct {
    TokenID   string
    Target    string // "self" / "enemy"
    DeltaMin  int8   // 最小变化 (可能为负)
    DeltaMax  int8   // 最大变化
}

// 计算技能预览
func (s *SkillSystem) Preview(w *World, caster EntityID, skillID string, targets []EntityID) *SkillPreview {
    tmpl := s.templates[skillID]
    preview := &SkillPreview{SkillID: skillID}
    
    // 1. 检查可用性
    preview.IsAvailable = s.checkCost(w, caster, tmpl.Cost)
    
    // 2. 评估静态效果
    for _, eff := range tmpl.StaticEffects {
        s.previewEffect(preview, eff, w, caster, targets)
    }
    
    // 3. 评估条件效果 (取最可能的情况)
    for _, ce := range tmpl.ConditionalEffects {
        probability := s.evalConditionProbability(ce.Condition, w, caster)
        if probability > 0.5 {
            for _, eff := range ce.Effects {
                s.previewEffect(preview, eff, w, caster, targets)
            }
        }
    }
    
    return preview
}
```

### 3. Observation 编码

```go
// RLEncoder - RL 观察值编码器
type RLEncoder struct {
    skillFeatureDim int // 每个技能的特征维度
    maxSkills       int // 最大技能数
}

func (e *RLEncoder) Encode(w *World, playerSide uint8) []float32 {
    var obs []float32
    
    // 1. 基础状态 (已有)
    obs = append(obs, e.encodeBaseState(w, playerSide)...)
    
    // 2. 全局技能特征矩阵 (关键)
    // 对每个角色，编码其所有技能的特征
    characters := w.GetCharacters(playerSide)
    for _, char := range characters {
        charSkills := e.encodeCharacterSkills(w, char)
        obs = append(obs, charSkills...)
    }
    
    // 3. 技能预览 (当前状态下各技能的实际效果预测)
    activeChar := w.GetActiveCharacter(playerSide)
    previews := e.encodeSkillPreviews(w, activeChar)
    obs = append(obs, previews...)
    
    return obs
}

// 编码角色技能 (固定维度)
func (e *RLEncoder) encodeCharacterSkills(w *World, char EntityID) []float32 {
    var result []float32
    
    skillComp, _ := GetComponent[SkillComponent](w, char)
    
    // 每个角色最多4个技能
    maxSkills := 4
    for i := 0; i < maxSkills; i++ {
        if i < len(skillComp.Skills) {
            skill := skillComp.Skills[i]
            feature := SkillFeatureDB[skill.ID]
            result = append(result, e.featureToVector(feature)...)
        } else {
            // 填充零向量
            result = append(result, make([]float32, 16)...)
        }
    }
    
    return result
}

// 编码技能预览 (动态)
func (e *RLEncoder) encodeSkillPreviews(w *World, activeChar EntityID) []float32 {
    var result []float32
    
    skillComp, _ := GetComponent[SkillComponent](w, activeChar)
    targets := []EntityID{w.GetActiveCharacter(w.GetOppositeSide())}
    
    for _, skill := range skillComp.Skills {
        preview := w.SkillSystem.Preview(w, activeChar, skill.ID, targets)
        
        // 预览编码 (8维)
        previewVec := []float32{
            b2f(preview.IsAvailable),           // 是否可用
            preview.PredictedDamageMin / 10.0,  // 最小伤害
            preview.PredictedDamageMax / 10.0,  // 最大伤害
            float32(preview.DamageElement) / 7.0, // 元素
            preview.PredictedHeal / 10.0,       // 治疗量
            b2f(preview.SummonPreview != nil),  // 是否召唤
            float32(len(preview.TokenChanges)) / 3.0, // token变化数
            // ... 其他预览特征
        }
        result = append(result, previewVec...)
    }
    
    return result
}

func b2f(b bool) float32 {
    if b {
        return 1.0
    }
    return 0.0
}
```

### 4. 动作空间设计

```go
// Action 编码 (整数ID)
// 方案1: 扁平化 (简单但维度高)
// [使用技能0, 使用技能1, 使用技能2, 切换角色1, 切换角色2, 使用卡牌0, ...]

// 方案2: 结构化 (推荐)
type Action struct {
    Type   ActionType // 0=技能, 1=切换, 2=卡牌, 3=结束
    Param  uint8      // 技能索引/角色索引/卡牌索引
}

// 动作掩码 (告诉RL哪些动作合法)
func (s *ValidActionSystem) GetMask(w *World, playerSide uint8) []bool {
    // 获取当前可用动作
    validActions := s.GetValidActions(w, playerSide)
    
    // 同时返回每个动作的预览信息
    // 这样RL不仅知道"可以用"，还知道"用了会怎样"
    
    mask := make([]bool, MaxActions)
    previews := make([]*SkillPreview, MaxActions)
    
    for i := 0; i < MaxActions; i++ {
        mask[i] = false
    }
    
    for _, act := range validActions {
        idx := encodeActionIndex(act)
        mask[idx] = true
        
        if act.Type == ActionUseSkill {
            previews[idx] = s.previewSkill(w, act)
        }
    }
    
    return mask, previews
}
```

## 完整 Observation 结构

```
Observation (总维度约 500):
┌──────────────────────────────────────────────────────┐
│ 基础状态 (100维)                                      │
│ - 我方3角色: HP, 能量, 附着, 装备 (3 * 15 = 45)       │
│ - 敌方3角色: HP, 附着 (公开信息) (3 * 10 = 30)        │
│ - 召唤物: 4个 * 5 = 20                               │
│ - 全局: 回合, 阶段, 骰子 (8)                         │
├──────────────────────────────────────────────────────┤
│ 技能静态特征 (192维)                                  │
│ - 我方3角色 * 4技能/角色 * 16维/技能 = 192            │
│ 告诉RL"这个角色有什么技能"                            │
├──────────────────────────────────────────────────────┤
│ 技能动态预览 (96维)                                   │
│ - 当前出战角色 * 4技能 * 6维/预览 = 96                │
│ 告诉RL"现在用这个技能会发生什么"                       │
├──────────────────────────────────────────────────────┤
│ 历史动作 (可选, 100维)                                │
│ - 最近10个动作 * 10维 = 100                           │
└──────────────────────────────────────────────────────┘
```

## 与 MCTS 结合

```go
// 提供快速模拟接口 (用于 MCTS rollout)
func (w *World) FastSimulate(action Action) *SimResult {
    // 1. 复制世界状态 (因为是值类型，很快)
    newWorld := w.Clone()
    
    // 2. 执行动作 (不触发Lua，只用预览近似)
    preview := newWorld.Preview(action)
    
    // 3. 近似应用效果
    newWorld.ApplyPreview(preview)
    
    // 4. 返回新状态和预估奖励
    return &SimResult{
        State:  newWorld,
        Reward: estimateReward(preview),
        Done:   newWorld.IsGameOver(),
    }
}

// 精确模拟 (用于最终执行)
func (w *World) ExactSimulate(action Action) *SimResult {
    // 完整执行，包括Lua
    newWorld := w.Clone()
    newWorld.Execute(action)
    return &SimResult{
        State:  newWorld,
        Reward: newWorld.CalculateReward(),
        Done:   newWorld.IsGameOver(),
    }
}
```

## 示例：RL 能学到什么

```python
# 观察值示例 (简化)
obs = env.reset()

# obs 包含:
# - 我方菲谢尔HP=10, 能量=3
# - 菲谢尔的技能特征: [0,1,0,0, 0.1,3,0,0, 1,0,0,0, 3,0,0,0]
#   解读: 战技,1点雷伤,有召唤,消耗3雷骰
# - 技能预览: [1.0, 0.1, 0.1, 0.43, 0.0, 1.0, 0.0, ...]
#   解读: 可用,1点伤害,雷元素,会召唤

# RL 策略网络可以学到:
# - "有召唤特征的技能 = 长期价值"
# - "能量满时用爆发 = 高收益"
# - "对方有火附着时用冰 = 触发反应"
```

## 实现优先级

1. **P0 - 技能静态特征**: 预计算所有技能的 feature vector
2. **P0 - 基础观察编码**: 包含技能特征在 observation 中
3. **P1 - 技能预览**: 运行时计算技能效果预测
4. **P1 - 动态预览编码**: 将预览加入 observation
5. **P2 - MCTS 快速模拟**: 基于预览的近似模拟

## 关键代码示例

```go
// 在观察值中包含技能信息
func (e *RLEncoder) Encode(w *World, playerSide uint8) []float32 {
    obs := make([]float32, 0, 512)
    
    // 基础状态
    obs = e.encodeBaseState(w, playerSide, obs)
    
    // 技能特征 (关键！)
    obs = e.encodeSkillFeatures(w, playerSide, obs)
    
    // 技能预览
    obs = e.encodeSkillPreviews(w, playerSide, obs)
    
    return obs
}

// 技能特征编码
func (e *RLEncoder) encodeSkillFeatures(w *World, side uint8, obs []float32) []float32 {
    chars := w.GetCharacters(side)
    
    for _, char := range chars {
        skills := w.GetSkills(char)
        
        // 每个角色最多4个技能
        for i := 0; i < 4; i++ {
            if i < len(skills) {
                feature := GetSkillFeature(skills[i].ID)
                obs = append(obs, feature.ToVector()...)
            } else {
                // 空技能填充0
                obs = append(obs, make([]float32, 16)...)
            }
        }
    }
    
    return obs
}
```

---

**核心思想**: 不把技能当黑盒，而是把"技能是什么"和"技能会怎样"都编码进观察值，让RL能直接学习到策略。
