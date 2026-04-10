# RL 卡牌对战 MVP v3 - 设计总览

## 项目结构

```
gicg_mono/
├── docs/                       # 设计文档
│   ├── overview.md             # 本文件：架构总览 + 索引
│   ├── dsl.md                  # DSL 规范（API、示例、卡牌分级）
│   ├── engine.md               # 引擎设计（伤害管道、回合流程、事件上下文）
│   ├── network.md              # 网络架构（Instruction Encoder、观测空间、shuffle）
│   ├── training.md             # 训练方案（预训练、RL 课程、奖励、超参）
│   └── acceptance.md           # 验收标准实施方案
├── engine/                     # Go 引擎
│   ├── go.mod
│   ├── counter/                # counter 数组、dispatch table
│   ├── hook/                   # hook 注册、执行
│   ├── pipeline/               # 伤害管道、回合流程
│   ├── lua/                    # LuaJIT 集成、DSL prelude
│   └── api/                    # cgo 导出 C API
├── data/                       # Lua DSL 游戏数据
│   ├── characters/             # 角色定义（counters + 技能）
│   │   ├── 赤蝶/
│   │   ├── 墨客/
│   │   ├── 猫咪/
│   │   ├── 刻师傅/
│   │   └── 天星/
│   ├── cards/                  # 卡牌定义（按学习难度分级）
│   │   ├── L1/ L2/ L3/ L4/ L5/ L6/
│   ├── system/                 # 系统规则 DSL
│   │   ├── reactions/          # 元素反应（蒸发、超载、融化...）
│   │   ├── death.lua           # 角色死亡 → 强制切换
│   │   ├── energy.lua          # 技能能量获取规则
│   │   ├── round.lua           # 回合开始/结束阶段规则
│   │   ├── draw.lua            # 抽牌规则
│   │   ├── timeout.lua         # 超时判负
│   │   └── food.lua            # 饱腹状态规则
│   └── patches/                # 平衡策略 DSL
├── training/                   # Python 训练层
│   ├── env/                    # Gymnasium 封装
│   ├── model/                  # 网络定义（Instruction Encoder + Grounding + Heads）
│   ├── pretrain/               # Instruction Encoder 预训练
│   ├── rl/                     # PPO + 自博弈
│   ├── eval/                   # 评估脚本
│   └── configs/                # 各阶段训练配置
└── rl_mvp_v3.txt               # 原始需求
```

## 架构

严格三层分离：

```
游戏数据 (Lua DSL)      <- 角色/卡牌/反应/系统规则，纯数据+逻辑
       | 加载
游戏引擎 (Go)           <- 通用执行器，不含任何具体游戏知识
       | cgo 导出 C API
训练层 (Python)          <- RL 训练，静态链接 Go 引擎 .so
```

- **Go 引擎**：通过 cgo 嵌入 LuaJIT（C 库），加载 DSL，执行游戏主循环，导出 C API
- **Lua DSL**：定义所有游戏内容，引擎代码不含任何具体数值
- **Python 训练层**：通过 ctypes 调用 Go 引擎，封装为 Gymnasium 环境，训练 PyTorch 模型

### LuaJIT 选型

使用 LuaJIT（C 库）而非 GopherLua（纯 Go），理由：
- 执行速度快 10~50 倍，RL 训练需要百万级 step
- Go 通过 cgo 链接 LuaJIT C API，性能可控
- 兼容 Lua 5.1 语法（DSL 中避免 5.3+ 特性如 `//`）

## 核心模型：Counter + Hook

- **Counter**：所有游戏状态统一为 flat 数组（HP、能量、护盾层数...无语义区别）
- **Hook**：所有效果逻辑统一为 flat 数组（技能、状态、反应...无类型区别）
- Hook 通过索引引用 counter，训练时 shuffle 破除位置依赖
- 详见 [DSL 规范](dsl.md)

## 两步决策

1. 从动态合法动作列表选 hook（动作）
2. 如需目标，从动态目标列表选 counter（目标）

## 实施顺序

1. Go 引擎核心（counter、hook dispatch、伤害管道、回合流程）
2. LuaJIT 集成（cgo、DSL prelude、文件加载、宏展开）
3. 角色与卡牌 DSL + 系统规则 DSL
4. 单元测试（覆盖所有游戏规则）
5. C API + Python Gymnasium 封装
6. AST 序列化（Lua AST → 张量）
7. Instruction Encoder 预训练（Stage P1-P3）
8. RL 课程训练（Stage 0-8）
9. 评估（验收标准 2-8）

## 文档索引

| 文档 | 内容 |
|------|------|
| [dsl.md](dsl.md) | Counter/Hook 模型、Scope、API、卡牌分级、完整 DSL 示例 |
| [engine.md](engine.md) | 伤害管道、回合流程、事件上下文、Go-Python 接口 |
| [network.md](network.md) | Shuffle 机制、观测空间、AST 序列化、Instruction Encoder、网络架构 |
| [training.md](training.md) | 预训练方案、RL 分阶段课程、奖励设计、算法配置、风险对策 |
| [acceptance.md](acceptance.md) | 8 项验收标准的具体实施方案 |
