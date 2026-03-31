# Code-as-Observation: 代码即观察方案

## 核心思想

> **不给人工特征，让网络自己从代码中学习。**

```
传统方案:                         Code-as-Observation:
- 人工设计16维特征                 - Lua代码直接tokenize
- 告诉网络"这会召唤"              - 网络自己看懂"create_summon"是什么意思
- 主观、可能遗漏                   - 客观、完整保留代码信息

Input: [HP][能量][...][技能特征]   Input: [HP][能量][...][SKILL_CODE_TOKENS]
```

## 1. 简化 Lua DSL

限制语法，保证可学习性：

```lua
-- 允许的语句类型 (共12种)

-- 1. 基础伤害
damage(TARGET, AMOUNT, ELEMENT)
-- 例: damage(ACTIVE_ENEMY, 2, PYRO)

-- 2. 治疗
heal(TARGET, AMOUNT)
-- 例: heal(SELF, 4)

-- 3. 召唤
create_summon(SUMMON_ID, USES, TRIGGER_PHASE, EFFECT)
-- 例: create_summon("oz", 2, END_PHASE, damage(ACTIVE_ENEMY, 1, ELECTRO))

-- 4. Token操作
add_token(TARGET, TOKEN_ID, AMOUNT)
consume_token(TARGET, TOKEN_ID, MAX_AMOUNT)
get_token(TARGET, TOKEN_ID)  -- 返回层数，用于条件

-- 5. 条件
if COND then ... end
-- COND可以是: has_token(), hp_lt(), hp_gt(), has_aura(), etc.

-- 6. 查询
query(QUERY_TYPE)  -- 返回实体列表
-- QUERY_TYPE: ACTIVE_ENEMY, ALL_ENEMIES, BACK_ENEMIES, SELF, ALL_ALLIES

-- 7. 循环
for entity in query(QUERY_TYPE) do ... end

-- 8. 变量 (仅限于skill函数内)
local x = ...

-- 9. 修改伤害 (用于被动)
modify_damage(DELTA)  -- +1, -1, etc.
change_element(NEW_ELEMENT)

-- 10. 抽牌/弃牌
draw_cards(N)
discard_cards(N)

-- 11. 切换角色
switch_to(TARGET)

-- 12. 返回
effects = { ... }
return effects
```

### 完整示例

```lua
-- 菲谢尔.lua
function skill()
    effects = {}
    table.insert(effects, damage(ACTIVE_ENEMY, 1, ELECTRO))
    table.insert(effects, create_summon("oz", 2, END_PHASE, 
        damage(ACTIVE_ENEMY, 1, ELECTRO)))
    return effects
end
```

```lua
-- 阿蕾奇诺普攻.lua
function skill()
    effects = {}
    dmg = 2
    element = PHYSICAL
    
    -- 消耗敌方token增伤
    enemy = query(ACTIVE_ENEMY)[1]
    debt = get_token(enemy, "blood_debt")
    if debt > 0 then
        consume = min(debt, 3)
        consume_token(enemy, "blood_debt", consume)
        dmg = dmg + consume
    end
    
    -- 元素转换
    if get_token(SELF, "life_debt") > 0 then
        element = PYRO
    end
    
    table.insert(effects, damage(ACTIVE_ENEMY, dmg, element))
    return effects
end
```

## 2. Tokenizer

将 Lua 代码转换为 token 序列：

```python
# Token 词汇表 (约100个token)
VOCAB = {
    # 关键字
    'function', 'end', 'if', 'then', 'for', 'in', 'do', 'local', 'return',
    
    # API函数
    'damage', 'heal', 'create_summon', 'add_token', 'consume_token', 
    'get_token', 'query', 'modify_damage', 'change_element', 'draw_cards',
    'discard_cards', 'switch_to', 'min', 'max', 'table_insert',
    
    # 目标
    'SELF', 'ACTIVE_ENEMY', 'ALL_ENEMIES', 'BACK_ENEMIES', 
    'ALL_ALLIES', 'TARGET_0', 'TARGET_1',  -- 支持多目标选择
    
    # 元素
    'PYRO', 'HYDRO', 'CRYO', 'ELECTRO', 'ANEMO', 'GEO', 'DENDRO', 'PHYSICAL', 'PIERCING',
    
    # 阶段
    'END_PHASE', 'START_PHASE', 'ROLL_PHASE',
    
    # 数值 (embedding)
    'NUM_0', 'NUM_1', 'NUM_2', 'NUM_3', 'NUM_4', 'NUM_5', 'NUM_6', 'NUM_7', 'NUM_8', 'NUM_9',
    'NUM_10', ...  -- 离散化数值
    
    # 符号
    '(', ')', '=', ',', '.', '[', ']',
    
    # 变量名 (特殊处理)
    '<VAR>',  -- 所有变量名映射为同一个token
    
    # 字符串 (技能ID等)
    '<STR>',  -- 所有字符串映射为同一个token
    
    # PAD/UNK
    '<PAD>', '<UNK>',
}

class SkillTokenizer:
    def __init__(self):
        self.vocab = {tok: i for i, tok in enumerate(VOCAB)}
        self.max_length = 128  # 最大代码长度
    
    def tokenize(self, lua_code: str) -> list[int]:
        """代码 → token IDs"""
        tokens = []
        
        # 简单词法分析
        words = self._split(lua_code)
        
        for word in words:
            if word in self.vocab:
                tokens.append(self.vocab[word])
            elif word.isdigit():
                # 数值离散化
                tokens.append(self._number_token(int(word)))
            elif word.startswith('"') or word.startswith("'"):
                # 字符串
                tokens.append(self.vocab['<STR>'])
            elif word.isidentifier():
                # 变量名
                tokens.append(self.vocab['<VAR>'])
            else:
                tokens.append(self.vocab['<UNK>'])
        
        # Padding
        while len(tokens) < self.max_length:
            tokens.append(self.vocab['<PAD>'])
        
        return tokens[:self.max_length]
    
    def _number_token(self, n: int) -> int:
        """数值离散化"""
        if n <= 10:
            return self.vocab[f'NUM_{n}']
        elif n <= 20:
            return self.vocab['NUM_10+']
        else:
            return self.vocab['NUM_BIG']
```

## 3. 网络架构

```python
import torch
import torch.nn as nn

class CodeObservedPolicy(nn.Module):
    """
    输入: 游戏状态 + 技能代码
    输出: 动作概率
    """
    def __init__(
        self,
        vocab_size=100,
        code_dim=64,          # 代码embedding维度
        state_dim=128,        # 状态维度
        hidden_dim=256,
        num_actions=20,       # 动作数
    ):
        super().__init__()
        
        # 代码编码器 (Transformer)
        self.code_embedding = nn.Embedding(vocab_size, code_dim)
        self.code_transformer = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(d_model=code_dim, nhead=4, batch_first=True),
            num_layers=2
        )
        self.code_pool = nn.AdaptiveAvgPool1d(1)  # 池化为固定长度
        
        # 状态编码器 (MLP)
        self.state_encoder = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        
        # 融合层
        self.fusion = nn.Sequential(
            nn.Linear(hidden_dim + code_dim, hidden_dim),
            nn.ReLU(),
        )
        
        # 输出头
        self.policy_head = nn.Linear(hidden_dim, num_actions)
        self.value_head = nn.Linear(hidden_dim, 1)
    
    def forward(self, state_vec, skill_codes):
        """
        state_vec: [batch, state_dim]
        skill_codes: [batch, num_skills, code_length]
        """
        batch_size, num_skills, code_len = skill_codes.shape
        
        # 编码所有技能代码
        codes_flat = skill_codes.view(-1, code_len)  # [batch*num_skills, code_len]
        code_emb = self.code_embedding(codes_flat)   # [batch*num_skills, code_len, code_dim]
        code_encoded = self.code_transformer(code_emb)  # [batch*num_skills, code_len, code_dim]
        code_pooled = self.code_pool(code_encoded.transpose(1, 2)).squeeze(-1)  # [batch*num_skills, code_dim]
        code_features = code_pooled.view(batch_size, num_skills, -1)  # [batch, num_skills, code_dim]
        
        # 编码状态
        state_feat = self.state_encoder(state_vec)  # [batch, hidden_dim]
        
        # 融合: 将状态与每个技能的代码特征拼接
        state_expanded = state_feat.unsqueeze(1).expand(-1, num_skills, -1)  # [batch, num_skills, hidden_dim]
        combined = torch.cat([state_expanded, code_features], dim=-1)  # [batch, num_skills, hidden_dim+code_dim]
        
        # 融合处理
        fused = self.fusion(combined)  # [batch, num_skills, hidden_dim]
        
        # 输出
        action_logits = self.policy_head(fused)  # [batch, num_skills, num_actions_per_skill]
        value = self.value_head(fused.mean(dim=1))  # [batch, 1]
        
        return action_logits, value
```

## 4. Observation 结构

```python
def get_observation(game_state, skill_codes):
    """
    观察值由两部分组成:
    1. 数值状态 (传统)
    2. 代码token (新)
    """
    
    # 1. 数值状态 (约100维)
    state_vec = encode_state(game_state)  # HP, 能量, 附着等
    
    # 2. 技能代码 (每个技能128维)
    # 当前出战角色的所有技能
    active_char = game_state.get_active_character()
    skill_tokens = []
    
    for skill in active_char.skills:
        tokens = tokenizer.tokenize(skill.lua_code)
        skill_tokens.append(tokens)
    
    # 填充到固定数量 (4个技能)
    while len(skill_tokens) < 4:
        skill_tokens.append([0] * 128)  # PAD
    
    return {
        'state': state_vec,           # [100]
        'skill_codes': skill_tokens,  # [4, 128]
    }
```

## 5. 训练策略

### 阶段1: 代码理解预训练

先让网络学习"代码→效果"的映射：

```python
# 预训练任务: 给定代码，预测技能效果
class CodeEffectPredictor(nn.Module):
    def __init__(self):
        self.code_encoder = CodeEncoder()
        self.effect_predictor = nn.Sequential(
            nn.Linear(code_dim, 64),
            nn.ReLU(),
            nn.Linear(64, num_effect_types),
        )
    
    def forward(self, code_tokens):
        code_feat = self.code_encoder(code_tokens)
        # 预测: 是否有伤害? 治疗? 召唤?
        return self.effect_predictor(code_feat)

# 训练数据: 所有技能的 (代码, 实际效果) 对
# 从技能数据库构建
```

### 阶段2: 策略训练

使用 PPO/A3C 训练：

```python
# 网络输入
obs = get_observation(state, skill_codes)
action_logits, value = policy_net(obs['state'], obs['skill_codes'])

# 动作选择 (mask掉不可用动作)
valid_mask = get_valid_actions(state)
action_probs = F.softmax(action_logits, dim=-1) * valid_mask
action = sample(action_probs)

# 执行动作，获得 reward
next_state, reward, done = env.step(action)
```

## 6. 优势分析

| 方面 | 人工特征 | Code-as-Observation |
|------|---------|---------------------|
| 客观性 | 主观设计，可能遗漏 | 客观，完整代码 |
| 泛化性 | 新机制需重新设计特征 | 网络自己学习新API |
| 可解释性 | 特征含义明确 | 网络内部表示，需分析 |
| 训练难度 | 易 | 难（需更多数据） |
| 性能 | 快（特征计算快） | 稍慢（需编码代码） |

## 7. 实际示例

### 网络学到的模式 (理想情况)

```
输入代码: "damage(ACTIVE_ENEMY, 2, PYRO)"
         ↓ Tokenize
序列: [DAMAGE, (, ACTIVE_ENEMY, NUM_2, PYRO, ), ...]
         ↓ Transformer
网络理解: "对敌方造成伤害" → 高攻击价值

输入代码: "create_summon('oz', 2, END_PHASE, ...)"
         ↓ Tokenize  
序列: [CREATE_SUMMON, (, STR, NUM_2, END_PHASE, ...), ...]
         ↓ Transformer
网络理解: "创建结束阶段触发物" → 延迟价值，可能用于combo

输入代码: "if get_token(SELF, 'life_debt') > 0 then ..."
         ↓ Tokenize
序列: [IF, GET_TOKEN, (, SELF, STR, ), GT, NUM_0, THEN, ...]
         ↓ Transformer
网络理解: "条件依赖自身状态" → 需要检查token层数
```

## 8. 实现步骤

```bash
# 1. 构建技能代码数据集
python scripts/extract_skill_codes.py  # 从API拉取，转换为简化Lua

# 2. 预训练代码理解
python train_code_pretrain.py  # 代码→效果预测

# 3. 训练策略网络  
python train_policy.py  # PPO with code observation

# 4. 评估
python evaluate.py  # 对比: 代码观察 vs 人工特征
```

## 9. 关键代码

```go
// Go 引擎: 提供代码和执行
package engine

type SkillCode struct {
    ID       string
    LuaCode  string           // 简化Lua代码
    Tokens   []int            // 预计算的token
    Bytecode []byte           // 编译后字节码
}

// 执行时
func (s *SkillSystem) Execute(skillCode SkillCode, ctx *Context) []Effect {
    // 直接执行预编译字节码，不解析代码
    return s.lua.Execute(skillCode.Bytecode, ctx)
}

// RL接口: 获取观察
func (w *World) GetObservation(forPlayer int) *Observation {
    obs := &Observation{
        State: encodeState(w, forPlayer),
    }
    
    // 添加当前可用技能的代码token
    activeChar := w.GetActiveCharacter(forPlayer)
    for _, skill := range activeChar.Skills {
        obs.SkillTokens = append(obs.SkillTokens, skill.Tokens)
    }
    
    return obs
}
```

---

**核心创新**: 不给网络"我们理解的游戏规则"，而是给它"游戏程序本身"，让它自己学会理解。
