# 网页对战

从仓库根目录运行：

```sh
npm --prefix web/frontend run build
.venv/bin/python -m uvicorn web.backend.app:app --host 0.0.0.0 --port 8080
```

打开 http://localhost:8080/live ，同局域网可使用服务器的局域网地址和8080端口。
“当前 RL 模型”由 `configs/web/semantic_live.toml` 同时指定模型类型、训练规则配置、checkpoint 和评估报告。网页与评估都通过 `training.core.matchup.loaders.load_player` 的语义适配器装载模型；严格验证训练产物指纹、报告中的 checkpoint SHA 和场景配置，每局创建独立模型与环境。模型未安装或与当前源码不兼容时，profile 会明确标记不可用。

队伍人数、角色池和双方是否允许重叠都来自 profile，profile 则读取服务选中的训练配置。每队编号1的角色先出战，P0/P1选择你控制的席位；牌组、骰子规则和回合上限也沿用同一训练配置。
行动列表将同一行动的支付组合合并，先选支付方式，再点击行动。点击手牌或角色为默认支付快捷操作。死亡后的替补选择使用实际等待输入的一方，不依赖行动权；对局记录显示双方行动。

仓库默认服务配置使用 `artifacts/live_models/semantic_rl/` 部署槽位，checkpoint 不随源码安装，因此新 checkout 会显示模型不可用。规则关联输入改变后 checkpoint 格式为 `semantic-q/2.0.0`；旧 `1.0.0` 权重不能重标或复制进该槽位，必须用当前源码生成新的模型与匹配评估报告，再更新服务配置。旧引擎格式的历史回放不做跨规则兼容；回放回归测试使用当前引擎生成的记录。
