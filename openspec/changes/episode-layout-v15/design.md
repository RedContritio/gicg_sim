# 设计

make_env_factory 的返回闭包新增可选 layout_seed，构造时使用该种子，reset仍控制对局随机性。
serial collector 从主种子和局序号派生四条随机流，每局创建新实例并关闭旧实例。
完整重建自然刷新静态观测、槽位归一化与遮罩；play_one_episode 的 game_start 刷新双方缓存。
不原地修改排列，避免引用错位。代价是逐局DSL装载，性能优化需独立验证。
collector状态仍保存局序号、主种子与实际探索/换边RNG；精确恢复测试覆盖新路径。
评估以32个独立游戏+布局scenario为采样单位，换边共享布局，bootstrap以scenario成对重采样。
异步、其他范式及旧periodic evaluator不在本次迁移范围；本轮配置关闭periodic eval。
