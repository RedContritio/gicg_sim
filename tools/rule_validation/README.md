# 可复用规则验证

从仓库根目录执行，需要先构建与当前源码一致的引擎动态库：

```bash
.venv/bin/python -m tools.rule_validation.run configs/rule_validation/lethal_attack.toml artifacts/rule_attack_check
.venv/bin/python -m tools.rule_validation.run configs/rule_validation/lethal_overload.toml artifacts/rule_overload_check --checkpoint MODEL.pt
```

输出目录必须尚不存在。第二条命令的模型须与当前源码兼容；目前适配 SemanticAgent 检查点。

## 新增场景

复制上述 TOML 示例，填写以下字段。同类场景无需再写 Python 脚本。

| 字段 | 含义 |
| --- | --- |
| `name` | 场景名称 |
| `pool` / `data` | 卡池及源数据目录，默认 `native_latest` / `data` |
| `patches` | 相对文件路径、唯一匹配原文 `before`、替换文本 `after`；可省略 |
| `scene.team_0/team_1` | 双方阵容 |
| `scene.card_pool` | 手牌池输入，默认空；使用 GicgEnv 的输入格式 |
| `scene.fix_dice` | 可选固定骰子 |
| `scene.seed/layout` | 对局种子 / 编号布局，默认 93700 / 7 |
| `scene.player` | 可选要求决策方 |
| `scene.prepare_budget` | 到达目标决策的准备步数上限，默认 32 |
| `actions` | 动作标签前缀列表；匹配所有支付方式 |
| `expected` | 每个所选动作都应满足的精确断言，支持点路径 |

例如 `"after.players.1.active_char" = 1` 检查结算后的敌方出战位置，`"hp_loss.1" = 10` 检查敌方队伍净生命损失。可检查 `before`、`after` 完整公开状态以及 `done`、`winner`、`pending`。不同动作需要不同预期时，分别建场景。

准备策略是优先结束回合，否则执行首个合法动作；它只适合能按此方式到达的场景。复杂多步设置可通过 Python API 构造环境，再复用 `measure` 和 `check`。

## 公共接口与边界

- `patches.apply`：先检查路径和唯一匹配，再复制所选卡池及系统规则到隔离目录；不修改正式牌库，记录补丁和数据 SHA。
- `outcomes.measure`：快照、执行动作、读取结果、恢复并释放快照；各候选从同一状态测量。
- `outcomes.choose`：按立即获胜或敌方净生命损失生成候选组偏好；支付方式结果不一致或最优并列时拒绝生成唯一标签。
- `policy.rank`：输出模型选择、候选组最高评分及其在所有合法动作中的排名。
- `run`：组合配置、执行和 JSON 报告；断言失败也保存已测结果及错误，进程返回失败。

环境断言结果与模型评分分别报告。模型选错不会伪装成引擎失败；净生命损失标签也不代表长期最佳策略。补丁场景验证的是模拟器是否遵循声明的预期，不能替代游戏内实测，尤其 B17 仍属用户暂定规则。

原 `semantic_training/rule_probe.py` 与 `rule_lessons.py` 已复用补丁、候选定位和引擎测量；课程数值矩阵及训练分割仍留在课程层。新增通用测量需求时扩展此包，避免各实验复制实现。

## 验证记录（2026-09-14）

13 项相关本地测试通过。56 上两份示例均通过，附带新规则预训练模型评分也成功输出；模型在这两个场景均将所选普攻排第一。这是工具端到端验证，不是对战强度验收。

完整对局的参数随机化与一次性训练入口见 [变体训练说明](VARIANTS.md)。
