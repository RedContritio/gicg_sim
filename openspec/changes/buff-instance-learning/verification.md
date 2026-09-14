# 验证记录（2026-09-11）

## 结果

- `GOCACHE=/private/tmp/gicg-review-go-cache go test -race ./gicg_engine/... ./gicg_mcts/... ./gicg_actor/...`
  全部通过，包含真实牌组的顺序、死亡归属、快照与观测容量回归。
- C shared library 已重建，Python 环境严格检查新的动态观测长度。
- `pytest -n 4 gicg_env/tests training/tests --ignore=training/tests/test_greedy_player.py -q`：
  **1178 passed, 6 skipped**。排除了已有昂贵的无节点上限 minimax 测试文件；本次未修改该算法。
- 最后补验五范式基础 smoke：**5 passed**；buff 学习、基线工具、Python continuation/error：**13 passed**。
- 完整 tier 初次 **7 passed / 3 failed**，定位到 AZ/CFR/PPO 环境工厂把 `card_pool=None`
  错转为空列表，导致显式牌组无法加载。保留 None 后，失败文件复验 **4 passed**
  （其中1项是已通过的同文件测试）。所有原失败项已关闭。
- 完整 tier 覆盖五范式训练/保存/恢复与异步进程；CFR 沿用仓库现有 smoke stub，
  只证明驱动与生命周期接通，不能据此声称 CFR 真实多头训练有效。真实 CFR 网络梯度另有单测。
- 费用辅助数据真实采样：每组20步、19条含活跃 buff；旧/新/留出三组分别评估。
  已完成一次混采反传、保存探针权重。只检查链路与有限输出，不把该短实验当作泛化结果。
- `ruff` 格式、相关新增模块 F401/F821、全训练路径 F821、`git diff --check`、OpenSpec 索引通过。
  仓库全局行数审计仍含已有超限文件；新增 Go/Python 非测试模块均不超过300行。

## 复现辅助训练

在仓库根目录：

```bash
.venv/bin/python -m tools.cards.rule_cost_probe collect /tmp/old.npz --cards 乘胜追击 速速茶点
.venv/bin/python -m tools.cards.rule_cost_probe collect /tmp/new.npz --cards 乘胜追击 荷花酥
.venv/bin/python -m tools.cards.rule_cost_probe collect /tmp/held.npz --cards 乘胜追击 荷花酥 速速茶点
.venv/bin/python -m tools.cards.rule_cost_probe fit --old /tmp/old.npz --new /tmp/new.npz --held-out /tmp/held.npz --output /tmp/probe.pt
```

探针默认维度32；向现有策略加载编码器时需指定相同 `--dim`，并严格检查层数/结构。
可在代码中直接把策略的 `hook_encoder`、`buff_encoder` 传给 `RuleCostProbe`，使监督梯度
更新同一组参数。生产微调另由策略训练流程调用；当前没有自动选择微调步数/学习率的调度器。

旧策略权重使用 `agent.load_for_adaptation(path)`，返回需要学习的新参数名；之后新建优化器。
严格 resume 保持原行为，不能用它伪装不同规则/观测版本的精确续训。

## 仍然存在的限制

- 以逸待劳 Q04 的反击 actor/目标归因仍需独立修复。
- 动态列表已驱动本轮迁移的费用/增伤/减伤/护盾修正；未把所有系统/回合批量 hook
  全部改写成逐实例执行，见 design.md。
- 每个 counter 只对应一个可叠加实例；完整文件 IR 作为规则上下文，尚非精简效果 AST。
- 新 ABI 有1024行线端容量，回放与训练按有效长度压缩；扩池仍要验容量。
- 旧手工 fixture 可缺少 buff 尾段；旧历史回放无法恢复真实产生顺序，不能当作完整新观测数据。
- 未进行正式策略训练、胜率对比或零样本/少样本泛化评测。
