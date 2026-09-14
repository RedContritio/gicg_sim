# 设计

动作引用继续采用 N×3，第三列按动作类别解释：SWITCH 为己方角色槽；CARD 为
0..5 己方、6..11 敌方目标；无目标为 -1。引擎 ActionCharRef 被 C API 与
Go actor 共同使用，避免两条采样路径漂移。

共享 ActorCritic 增加 12 槽 card_target_emb，仅对有目标的卡牌添加到规则动作向量，
然后叠加付款向量及归一化。属于架构/输入语义变更，旧 artifact 指纹失效；不复用
旧权重或数据。拆出 action_embedding.py 以满足文件大小约束。

回归用同牌同付款治疗受伤/满血角色，确认真实效果不同、动作引用不同、完整 Q 头
分数可不同且梯度到达目标 embedding；抹掉目标字段时两个分数必须完全相同。
Go 表驱动覆盖双方己方/敌方全部槽位。学习任务协议见 protocol.md。

超载修复仅统一为现有 force_switch_next builtin 名称，并同步 tokenizer 名称。
保留同一个语义 opcode，不修改本轮强制切换行为。强制切换是否触发 HookSwitch
存在规范与实现差异，需要单独审计后处理，不能用此次命名修复声称已解决。
