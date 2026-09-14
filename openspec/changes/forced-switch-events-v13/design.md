# 实现设计

Game.ForceSwitchTo 验证存活目标，实际改变出战角色时复用 executeSwitch：
Forced=true、ActForcedReaction，派发 HookSwitch 并处理延迟效果，不扣骰、
不执行主动行动准备、不额外翻转行动权。目标未变不派发事件。
force_switch_next 和 set_active_char 均使用它；现有死亡切换已派发 HookSwitch，
不再增加第二次派发。只针对主动切换的效果仍可按 ActionContext 过滤。

补双方视角超载切换事件次数、仅一人存活不触发、显式设置同位不触发、延迟效果
执行及骰子/行动权保持测试。规则变更后旧 artifact 指纹不兼容，条件学习从零复跑。
网络架构与 v12 相同，沿用其五范式完整 smoke，加最终广泛回归。
