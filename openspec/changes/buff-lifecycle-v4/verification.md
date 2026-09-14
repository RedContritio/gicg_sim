# v4 验证记录（2026-09-11）

- 最终 `go test -race ./gicg_engine/... ./gicg_mcts/... ./gicg_actor/...`：通过。
- 重建 `gicg_env/libgicg.dylib`；Python 环境与训练默认套件：1179 passed、6 skipped。
  命令：`.venv/bin/python -m pytest -n 4 gicg_env/tests training/tests --ignore=training/tests/test_greedy_player.py -q`。
  延续 v3 验收约束，排除含无界 minimax 搜索的慢测试文件；未把它记为通过。
- 独立层次数、期限、实际消费、快照恢复、写入回调归属与原语 IR：通过。
- 双方普通 buff/召唤物交错顺序、致死终止、蝶印后台/死亡、事件内重建：通过。
- 观测实例值、精确 hook 绑定、结束排序组、生命周期编号不可见：通过。
- BuffEncoder 顺序敏感、槽号置换、padding、梯度、旧权重适配：6 passed。
- 基线工具单测：5 passed；OpenSpec 索引、相关 Python format/F821、`git diff --check`：通过。
- 全仓行数审计仍有已有超限文件；新增实现文件满足 300 行限制。本轮将事件帧定义拆出 game.go。

## 完整训练烟雾验收

`.venv/bin/python -m pytest -m smoke_full training/tests/ -q`：10 passed（677.77 秒）。
完整烟雾测试用于训练、保存与恢复接口验收；CFR 完整烟雾沿用现有测试桩，不能等同真实策略训练。
所有烟雾产物使用测试临时目录，没有启动正式训练或远程实验。

## 尚未证明

未完成新卡零样本胜率、微调样本效率、旧环境遗忘或完整规则组合穷举。
旧的全文件规则上下文已替换为实际绑定 hook，但任意 hook 内多分支仍需网络学习。
未迁移的非当前配置角色不能因属于同一个卡池就视为已验证。

新基线 `current-training-custom-v4` 已冻结 672 个文件，校验 MATCH；旧版 manifest 未更新。
