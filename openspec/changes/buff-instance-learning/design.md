# 设计与接口

## 执行与状态

`Game.BuffDefinitions` 是加载时固定的定义表，绑定规则来源、主 counter、持续回合、
进度及死亡清理策略。`Game.Buffs` 只保存当前存活实例，列表顺序即产生顺序。
激活追加，耗尽/过期移除；重新激活追加到末尾。叠加次数保留原实例位置；引用型装备更换
重新排到末尾。次数等数值继续由 counter 存储，避免两份数值状态互相漂移。
当前实现每个注册 counter 最多对应一个实例；独立叠层必须用独立 counter/定义表达。

DSL：`register_buff(counter, {duration=..., progress=..., expires_round_end=true, remove_on_death=true})`。
修正 hook 用 `on_action_prepare({order=counter}, fn)` 等选项绑定实例，`priority` 划分阶段内类别。
固定系统 hook 仍按管线执行；注册了 `order` 的同类修正效果按列表顺序执行。
回合边界的既有系统遍历与批量衰减不改成逐实例 hook，不应把它误认为所有 DSL hook 都已迁移。
事件开始时确定有资格参与的 counter；提前耗尽的效果在轮到它时跳过。

伤害类别顺序：条件归零（荷花酥，priority=100）、普通减伤（水云，默认0）、护盾阶段。
减到零后停止后续减伤。减费实际不改变费用时不记为应用，避免消耗无收益效果。
快照、克隆、重置及 checkpoint 保存/恢复列表；checkpoint 身份包含静态定义布局。

## NN 输入

动态观测尾部追加 `1024 × 11`，每个实例与对应规则文件中的有效 hook 形成一行：

`valid, relative_owner, character, value, duration, progress, order, hook_slot, trigger, category, death_bound`

- 队伍 char=-1，永久 duration=-1；owner 为己方0/敌方1/全局-1。
- order 为当前列表位置，不是无限增长的时间戳。
- hook_slot 引用同一份静态 IR 编码；一个定义可以关联多个规则来源，避免共享装备 counter 覆盖。
- 以完整文件规则作为上下文，尚未把每个 buff 的程序最小化拆分；可能包含同文件其他效果。
- 超过1024行显式失败，不截断。扩池前必须先统计容量并升级观测版本。容量回归覆盖当前配置所有注册实例同时存在的保守上界。
  Python 解析后只保留有效前缀，回放按实际长度存储，批处理只补齐到本批最长序列，避免存储1024行空白。

`BuffEncoder` 将规则嵌入与实例字段相加，经 attention/掩码池化后加入决策状态。
空列表输出零向量。规则槽位重排且同步更新引用，应保持输出不变；交换实际顺序应可区分。
动作/状态的原有输入保留。这里增加了效果语义，尚不等于完整、与命名完全无关的卡牌 DSL 编码。

AZ/PPO/DMC/BC 共用 ActorCritic；CFR 自己的 trunk 接同一 BuffEncoder。
采样、批处理、CFR reservoir 持久化均携带 buff 行。旧的手工测试 batch 可缺省为空列表；
真实 GicgEnv 校验完整长度，旧动态 ABI 必须重建，旧回放不应当作有完整 buff 状态的数据使用。

## 微调与新原语

`AgentBase.load_for_adaptation(path)` 独立于严格 resume：保留旧参数，仅允许新增 buff 模块及
原语 opcode/operand embedding 追加行，其他缺键/多键/维度变化报错。新模块/新行保留初始化，
重新创建优化器。原语编号只追加，不能复用旧编号。观测 IR 结构变化不由该函数自动迁移。

`RuleCostProbe` 直接接收共享 HookEncoder/BuffEncoder，监督当前合法操作的实际骰子总费用。
`tools.cards.rule_cost_probe collect` 用真实引擎生成样本，`fit` 混合旧/新环境并分别报告
旧环境、新环境、留出组合误差；训练与留出组合重叠时报错。探针输出可单独加载到相同结构
策略的两个 encoder；代价预测头不进入对局决策。

这是首个辅助任务，未覆盖下一状态、触发判断、伤害与资源长期价值；训练数据还应增加有意
构造的边界场景。随机采样出现过 buff 不代表覆盖了所有触发条件。

新增机制流程：执行原语与明确规则 → 回归测试 → 稳定 token/结构化参数 → 辅助标签 →
旧新混合微调 → 旧池回归、新池适应、未见组合三类评估。没有承诺零样本成功或固定算力预算。
