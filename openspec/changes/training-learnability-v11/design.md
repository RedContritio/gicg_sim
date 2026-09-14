# 实验设计与实现

首次执行前的固定预算见 protocol.md；执行结论见 results.md。

readiness_cost 复用现有 RuleCostProbe 与引擎费用采集，训练集合只含两组基础牌，
组合组只评估。每个种子重新创建网络和优化器；不从评估结果挑选检查点。
每个动作类别使用训练集均值构造基线，以识别“只猜动作类型”获得的收益。

tactical_data 用 readiness_tactics 的正式配置和合法探索产生状态，逐个克隆试走
合法动作后读取公开 HP。不同付款动作保留对应位置；克隆关闭，原状态不变。
直接检查 native 步进返回码，拒绝非法编号或未知返回码。该标签仅评价已发生的一步
效果，暂停和跨回合自动推进由现有引擎决定，不构造虚假 Monte Carlo 终局标签。

tactical_learning 复用 capture_obs、collate_batch 和正式 DMC 网络，训练损失为
全部并列最优动作的均匀软标签交叉熵。付款变体保留，不把第一个最优动作设为唯一答案。
网络输入没有 utility 或全信息 view，只有既有 masked observation 和规则定义。
这是一条监督辅助实验路径，不替代 tools.runs.train 的正式 RL 生命周期。

报告和 artifact 带协议哈希、来源指纹、种子及动作前缀；输出目录只允许新建。
费用标签数据用 save_dataset，战术变长数组用 save_checkpoint 保存；后者是数据容器，
不是可续训模型。旧 epoch 权重和数据不得加载。

后续先做状态条件对照和更长价值范围。若调整网络架构或观测，另建变更并执行五范式
完整 smoke；本轮无此变更，只执行五范式默认 smoke 与实验相关回归。
