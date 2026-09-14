# 五角色 2v2 八种行动牌课程

2026-09-13 用户确认启用；强度主标准为 D2，D1 作梯度检查，D3 不进入本轮。

## 环境与协议

配置：`configs/dmc/semantic_duo_tactics.toml`。继承五角色随机不重复 2v2、10 回合裁决及随机骰子。双方明确使用同一套 16 张牌：测试卡_增幅、测试卡_碎片、美味烧鸡、佛跳墙、荷花酥、反制、玄冰、乘胜追击，每种两张。padding target 为 16，但实际不插入碌碌无为。以逸待劳和速速茶点仍不进入训练/选模，留作适应测试。

原配置 blanket 禁止随机角色加 explicit deck，现开放双方相同且非空的明确牌组；非对称/单侧依旧拒绝，卡牌适用性仍由每次引擎建局校验。全部 15 组不相交队伍对阵、双方、重复 reset 的实际手牌+牌堆多重集已在本机及 56 验证。不是放宽天赋/武器适用性。

全流程在 56（D:/gicg_goal）运行，解释器 D:/gicg_dev/.venv/Scripts/python.exe，16 workers：

1. 新生成 512 局 D2 示范，4000 步 BC；不沿用旧小牌组权重/经验。
2. BC 作为冻结 KL 锚点，终局奖励 RL 8×128 局；训练对手仍 D1，保留原算法预算以先观察扩池影响。
3. RL seed160000；D2 开发集 seed161000，120 场景×双侧×2 布局。选最高开发分的 RL 轮次，并列取最早；独立集不参与选择。
4. 冻结选择后，seed162000 360 场景×双侧×2 布局，分别评估 BC/RL 对 D2、D1。每项 1440 局，配对场景聚类区间。
5. seed163000，60 场景四布局动作/支付一致性检查。

D2 开发集选模由 RL 新增 `dev_depth` 参数支持，默认仍为 D1，恢复设置包含该参数。旧 checkpoint 的参数默认按 D1 解释；本轮配置层源码变更使生产指纹改变，新权重严格使用新指纹，不重标旧权重。旧网页固定模型若重新加载会触发指纹保护，后续网页优化时再接入验证过的新候选；没有把旧模型自动替换成未验证模型。

## 执行状态

本机 31 项 Python 回归及相关 Go 卡牌/费用/buff 测试通过；56 新牌组两项真实引擎检查通过。
首次启动前自动同步漏掉未跟踪目录内的新入口，未产生训练；已补传 tactics.py 和 rl.py。
正式流程入口 `tools.experiments.semantic_training.tactics`，控制目录 `artifacts/semantic_duo_tactics`，result.json 持续记录 stage/status。源代码与配置归档为 source.tar.gz，训练仍注册独立 run、保存 cfg_resolved 和 checkpoints。

启动命令（通过仓库 wrapper）：

```sh
.venv/bin/python -m tools.runs._ssh --stream --timeout 14400 configs/dmc/semantic_duo_tactics.toml -- D:/gicg_dev/.venv/Scripts/python.exe -X utf8 -u -m tools.experiments.semantic_training.tactics configs/dmc/semantic_duo_tactics.toml artifacts/semantic_duo_tactics --workers 16
```

新牌池结果不得与旧牌池 56.11% 直接比较；尚未产出本轮强度结论。

## 首轮完成结果

56流程正常结束，耗时1705秒。BC run000013，RL run000014；D2开发集选第4轮。独立360场景×双侧×2布局：BC对D1 59.31% [55.69,62.92]、对D2 33.89% [30.83,37.08]；RL对D1 59.86% [56.53,63.19]、对D2 32.36% [29.17,35.56]。本轮只达到对D1优势，未达到D2目标；RL没有改善新卡组强度。4938状态、14814次布局对比动作/支付100%一致。结果已拉回 artifacts/semantic_duo_tactics。后续扩大课程与示范预算、加入D2训练对手，不能直接使用旧小池56.11%成绩作新卡组证明。
