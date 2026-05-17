> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **OBSOLETE**(自标,phase 命名遗留)
> - 原文撰写时用 `phase{0-5}_{a,b,c,d}` 课程体系(PPO pre-AZ era)
> - 已被 2026-04-24 paradigm pivot 后 Stage 0-5 curriculum 取代,**curriculum 又被 ADR-0009/0010 closed**
> - 标准 1-3(Go 测试套件 + DSL 正确性)仍有效;标准 4-8 待 P2 unified-training-pipeline 后重写
>
> 当前活跃 acceptance criteria 见 `openspec/specs/training-architecture/` + paradigm dossier(P1-T8)。

---

# 验收标准实施方案

> **⚠️ OBSOLETE 阶段命名 (2026-04-26 标注)。** 本文撰写时用 `phase{0-5}_{a,b,c,d}` 课程体系
> (PPO pre-AZ era),该体系已被 2026-04-24 paradigm pivot 后的 Stage 0-5 curriculum
> 取代。标准 1-3 仍有效 (Go 测试套件 + DSL 正确性);标准 4-8 待 curriculum 推进到 Stage 4-5
> 后重写映射。
>
> **⚠️ 远期规划文档。** 本文是跨多个未来阶段的长期验收计划。当前活跃 plan 见
> [`curriculum/plan.md`](curriculum/plan.md)。

## 标准 1：环境正确性

全面单元测试（Go 端 + Lua 测试文件）。

测试类别：
- 技能效果：每个角色 x 每个技能，验证伤害/治疗/状态创建
- 元素反应：全部 7 种反应，验证伤害加成、强制切换、冻结等
- 回合流程：AP 重置、抽牌、结束阶段顺序、超时
- 胜负判定：全部角色死亡、超时平局判定
- 动作合法性：AP 检查、冻结检查、食物饱腹、装备类型匹配
- 伤害管道：穿透、护盾吸收、连锁伤害、反应优先级
- 复杂交互：解冻优先级、泼墨连锁、正气拦截、蝶印回合结算

## 标准 2：学习验证

在每个训练阶段追踪：
- 平均对局回合数（应随训练下降并趋于稳定）
- vs Random 胜率（目标 > 90%）
- vs Greedy 胜率（目标 > 70%）

## 标准 3：决策分析

引擎记录每步的动作、counter 状态和 hook 触发。Python 脚本生成人类可读的对局回放。

分析维度：技能选择模式、切换时机、卡牌使用时机、结束回合时机。
定性检查：agent 是否学会 combo（如蝶火 → 枪获得加伤）。

## 标准 4：1v1 平衡性

Stage 5 毕业检查。5x5 round-robin 锦标赛，每对局 1000 局。
计算每个角色的聚合胜率，目标：最高与最低之差 < 20%。

## 标准 5：2v2 最强阵容

Stage 7 毕业检查。10x10 阵容 round-robin。
排名阵容聚合胜率，分析 top 阵容的配合和策略。

## 标准 6：牌分数评估

Stage 6 中执行。对每张牌：
1. 基准：完整卡牌池训练的 agent 胜率
2. 禁牌：移除该牌后评估胜率
3. 分数 = 禁牌后胜率下降幅度

构建偏序关系。

## 标准 7：平衡策略适应

Stage 8 中执行。平衡 patch 以锁定支援指示器形式实现。
训练时随机采样 1-4 个 patch。评估时使用 held-out 组合。

## 标准 8：Patch 与直接修改等价性

对若干 patch，分别用 patch 方式和直接修改 DSL 方式运行评估。
比较 agent 决策和对局结果，应统计一致。
