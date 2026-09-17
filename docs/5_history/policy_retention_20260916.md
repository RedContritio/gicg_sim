# 策略保留对照：选择 full 进入 RL

2026-09-16。56 的 `artifacts/policy_retention/retention_resume4/completion.json`
为 complete，六臂、440 局确认面板和凯亚探针均已结束，总耗时 2074.92 秒。
本实验固定一个预热检查点、一份配对数据、一个训练 seed 和一套确认面板，用于选择下一轮
RL 初始化；不是 D2 强度验收，也没有跨训练 seed 稳定性。正式六臂完成后又执行了
`isolated_rule` 追加臂；它只验证隔离梯度路径，未进入面板、探针或选臂比较。

## 选择结论

`full` 与 `anchored` 同时通过规则留出学习和“相对 warmup 无明确退化”两项检查。
两者直接比较为 `anchored - full = +1.36` 个百分点，场景聚类 95% 区间
`[-6.82,+9.55]`，没有证据说明 `anchored` 优于 `full`。`full` 不含 KL 锚点和梯度门控，
机制更简单；按预定判断规则，选择：

**下一轮等预算 RL 从 `full_policy.pt` 开始。**

`anchored` 是有效的保护机制候选：门控实际触发 692/1500 次，规则和策略检查都通过。
只有后续明确要求显式 KL 与冲突门控时，才值得用新 seed 与 `full` 再做一次独立直接比较。
`96600` 已参与本轮选臂，不能复用于晋级验收。

## 固定来源

| 项 | 值 |
|---|---|
| 源码指纹 | `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15` |
| warmup checkpoint | `artifacts/202609160006_000008_semantic_warmup/ckpts/latest.pt` |
| warmup SHA256 | `aa065296d5271ca52a99d4a267d1134374764615c63adf8a0982a8bc3c552bba` |
| 汇总 | `artifacts/policy_retention/retention_resume4/completion.json` |
| 直接比较 | `artifacts/policy_retention/retention_resume4/direct_compare/*.json` |
| 训练 | 六臂共用 360 对数据、2048 teacher rows、1500 步，seed `95000` |
| 确认面板 | 110 场景 x 双方席位 x 2 布局 = 440 局/模型，seed `96600` |

六个训练报告分别是：

| 臂 | 运行目录 |
|---|---|
| `full` | `artifacts/202609160202_000021_retention_full/report.json` |
| `frozen` | `artifacts/202609160204_000022_retention_frozen/report.json` |
| `probe_then_finetune` | `artifacts/202609160205_000023_retention_probe_then_finetune/report.json` |
| `full_lowlr` | `artifacts/202609160206_000024_retention_full_lowlr/report.json` |
| `replay` | `artifacts/202609160208_000025_retention_replay/report.json` |
| `anchored` | `artifacts/202609160214_000026_retention_anchored/report.json` |

追加隔离臂的报告位于
`artifacts/202609160659_000031_retention_isolated_rule/isolated_rule.pt`，其
`completion.json` 为 complete，源码指纹、warmup 和训练 seed 与正式六臂相同。

## 规则学习

表中为 `states` 和 `values` 留出集的终值；方向准确率只统计实际发生变化的样本。
`delta_within_half` 是差值误差不超过 0.5 的比例。

| 臂 | states MAE 初始 -> 终值 | states 方向 | states <=0.5 初始 -> 终值 | values MAE 初始 -> 终值 | values 方向 | values <=0.5 初始 -> 终值 |
|---|---:|---:|---:|---:|---:|---:|
| `full` | 3.150 -> 0.409 | 100.0% | 20.0% -> 87.8% | 3.820 -> 0.466 | 95.9% | 18.9% -> 60.0% |
| `anchored` | 3.150 -> 0.677 | 100.0% | 20.0% -> 70.0% | 3.820 -> 0.637 | 98.6% | 18.9% -> 64.4% |
| `frozen` | 3.150 -> 1.789 | 22.2% | 20.0% -> 20.0% | 3.820 -> 1.698 | 42.5% | 18.9% -> 18.9% |
| `probe_then_finetune` | 3.150 -> 1.795 | 94.4% | 20.0% -> 20.0% | 3.820 -> 1.679 | 93.2% | 18.9% -> 18.9% |
| `full_lowlr` | 3.150 -> 1.698 | 98.6% | 20.0% -> 20.0% | 3.820 -> 1.574 | 94.5% | 18.9% -> 18.9% |
| `replay` | 3.150 -> 1.070 | 98.6% | 20.0% -> 28.9% | 3.820 -> 1.087 | 97.3% | 18.9% -> 31.1% |

只有 `full` 和 `anchored` 在 states、values 两个划分上同时提高了变化方向准确率和
差值误差不超过 0.5 的比例。`frozen` 的绝对误差下降但方向变差；`probe_then_finetune`
和 `full_lowlr` 没有改善差值误差落在 0.5 内的比例；`replay` 有改善，但幅度低于前两者。
`probe_then_finetune` 的 probe 退出点 states/values MAE 为 1.941/1.957，后 750 步继续下降，
不能只截取冻结阶段。

### 追加 isolated_rule

`isolated_rule` 冻结 Q 分支，在零初始化残差 adapter 上向规则头提供 `state/actions`，只训练
adapter 和规则头。1500 步后 Q 参数逐元素零漂移，CKA 为 1.00000，但规则学习没有形成有效
方向：`states` 变化方向准确率从 37.5% 降到 29.2%，`values` 从 46.6% 降到 43.8%；
`train` 从 38.2% 降到 26.4%。以下与六臂终值直接比较：

| 臂 | states MAE | states 方向 | values MAE | values 方向 | train MAE | train 方向 |
|---|---:|---:|---:|---:|---:|---:|
| `full` | 0.409 | 100.0% | 0.466 | 95.9% | 0.398 | 100.0% |
| `anchored` | 0.677 | 100.0% | 0.637 | 98.6% | 0.610 | 100.0% |
| `replay` | 1.070 | 98.6% | 1.087 | 97.3% | 1.047 | 98.6% |
| `isolated_rule` | 1.661 | 29.2% | 1.540 | 43.8% | 1.663 | 26.4% |
| `frozen` | 1.789 | 22.2% | 1.698 | 42.5% | 1.790 | 23.6% |

该臂的 MAE 下降但变化方向变差，且 `delta_within_half` 没有超过初始值，表现接近向保守
均值收缩，而不是学会配对后果方向。因此 `isolated_rule` 不进入适配器推理链路、面板和探针，
也不替换 `full`。它证明冻结 Q 可以消除参数漂移，却没有解决规则监督需要的最小有效学习。

本轮没有执行同容量 control，因此“独立参数路径”和“仅增加 adapter 容量”两个因素尚未
严格分离。即使执行该 control，也不能改变当前否决 `isolated_rule` 的结论；它只影响对
独立路径收益的因果归因。

## 策略保留

六臂和 warmup 都完成 440 局，全部无平局。得分沿用胜 1、负 0、平 0.5；“超时”按环境裁决，
单列其中判胜和判负的局数。

| 模型 | checkpoint SHA256 前缀 | 得分 | 对 warmup 差值，场景聚类 95% | 席位 0 | 席位 1 | 胜-负 | 超时，胜/负 |
|---|---:|---:|---|---:|---:|---:|---:|
| `warmup` | `aa065296...` | 30.91% | reference | 32.73% | 29.09% | 136-304 | 36，16/20 |
| `full` | `db2d9968...` | 30.00% | -0.91% `[-8.64,+6.82]` | 28.18% | 31.82% | 132-308 | 32，14/18 |
| `frozen` | `caccfb03...` | 30.91% | 0.00% `[0,0]` | 32.73% | 29.09% | 136-304 | 36，16/20 |
| `probe_then_finetune` | `ac84356e...` | 26.36% | -4.55% `[-11.36,+2.27]` | 25.45% | 27.27% | 116-324 | 46，18/28 |
| `full_lowlr` | `e93d1651...` | 19.55% | -11.36% `[-17.73,-5.45]` | 25.45% | 13.64% | 86-354 | 40，2/38 |
| `replay` | `b9bfc00d...` | 21.36% | -9.55% `[-17.27,-1.82]` | 20.91% | 21.82% | 94-346 | 30，4/26 |
| `anchored` | `28bbdab9...` | 31.36% | +0.45% `[-5.00,+5.91]` | 35.45% | 27.27% | 138-302 | 40，16/24 |

`full_lowlr` 和 `replay` 相对 warmup 明确退化。`full`、`frozen`、`anchored` 和
`probe_then_finetune` 的区间跨 0，未证明确实退化；其中只有 `full` 与 `anchored`
同时通过规则学习检查。所有模型的单个面板区间下界均低于 50%，没有完成对 D2 的强度晋级。

## 臂对臂比较

15 组比较都使用相同的 110 个物理场景；每个场景含双方席位和两个布局，即 4 局。
下表统一写“前者 - 后者”及其场景聚类 95% 区间。磁盘 JSON 使用
`candidate - reference`，区间也按相同的配对场景重采样。

| 比较 | 差值及其 95% 区间 |
|---|---:|
| `anchored - frozen` | +0.45% `[-5.00,+5.91]` |
| `anchored - full` | +1.36% `[-6.82,+9.55]` |
| `anchored - full_lowlr` | +11.82% `[+4.55,+19.09]` |
| `anchored - probe_then_finetune` | +5.00% `[-2.27,+12.27]` |
| `anchored - replay` | +10.00% `[+1.82,+18.18]` |
| `frozen - full` | +0.91% `[-6.82,+8.64]` |
| `frozen - full_lowlr` | +11.36% `[+5.45,+17.73]` |
| `frozen - probe_then_finetune` | +4.55% `[-2.27,+11.36]` |
| `frozen - replay` | +9.55% `[+1.82,+17.27]` |
| `full - full_lowlr` | +10.45% `[+3.64,+17.27]` |
| `full - probe_then_finetune` | +3.64% `[-3.64,+11.36]` |
| `full - replay` | +8.64% `[+0.91,+16.36]` |
| `full_lowlr - probe_then_finetune` | -6.82% `[-12.27,-1.36]` |
| `full_lowlr - replay` | -1.82% `[-8.64,+5.00]` |
| `probe_then_finetune - replay` | +5.00% `[-2.27,+11.83]` |

`full` 明确优于 `full_lowlr` 和 `replay`；`anchored` 也明确优于这两臂。
`anchored - full` 和 `anchored - frozen` 都跨 0，且点估计最多只差 1.36 个百分点。
因此不能把 `anchored` 的点估计排名写成已证实的策略收益，也不能用它的门控触发次数
替代臂对臂效果证据。

## 机制与探针

原始 `report.json.trace` 只记录余弦和 EMA，无法区分配对回归究竟改写了哪条表征路径。
补充的离线诊断固定同一 warmup 和六臂 checkpoint，使用 720 个配对行、512 个 teacher
行和 seed `95000`。产物为
`artifacts/policy_retention/retention_resume4/retention_diagnostic_20260916_grouped.json`，
SHA256 `a985686ed1624699fb2c9e5a9956d51fff52462de0d235c00801141f2bf125ab`。它只解释
本轮 checkpoint 的梯度与输出几何，不是新的强度评估。

### 漂移与门控

| 臂 | 门控拦截 | 未定义余弦次数 | 参数漂移均值/最大 | CKA |
|---|---:|---:|---:|---:|
| `full` | 0 | 0 | 0.00626 / 0.16953 | 0.99557 |
| `frozen` | 0 | 31 | 0 / 0 | 1.00000 |
| `probe_then_finetune` | 0 | 16 | 0.00107 / 0.02647 | 0.99634 |
| `full_lowlr` | 0 | 0 | 0.00213 / 0.05488 | 0.98366 |
| `replay` | 0 | 0 | 0.00941 / 0.45136 | 0.99268 |
| `anchored` | 692 | 0 | 0.00629 / 0.20767 | 0.98965 |

`anchored` 的门控按定义执行，但平均参数漂移与 `full` 几乎相同，说明“触发门控”本身
不等于完整的零漂移保护。`frozen` 参数逐元素不变，规则学习却失败，也不能靠零漂移晋级。
Q head 相对漂移为：`full`、`frozen`、`probe_then_finetune`、`full_lowlr` 均为 `0`；
`replay` 为 `0.26312`，`anchored` 为 `0.10414`。

### 配对语义与策略输出

表内排名是配对数据所选动作在 Q 排序中的全动作平均名次；teacher 的 tied margin
为候选动作集中最佳动作相对集合外的领先量。

| 臂 | pair KL | pair top1 | pair selected rank | teacher KL | teacher top1 | teacher tied margin |
|---|---:|---:|---:|---:|---:|---:|
| `full` | 3.275 | 36.8% | 8.93 -> 4.33 | 1.177 | 53.3% | 0.760 |
| `frozen` | 0 | 100.0% | 8.93 -> 8.93 | 0 | 100.0% | 1.149 |
| `probe_then_finetune` | 0.083 | 75.0% | 8.93 -> 9.04 | 0.084 | 69.3% | 1.186 |
| `full_lowlr` | 0.409 | 58.3% | 8.93 -> 9.31 | 0.326 | 55.7% | 1.210 |
| `replay` | 0.494 | 46.3% | 8.93 -> 8.16 | 0.273 | 62.7% | 1.422 |
| `anchored` | 0.869 | 68.5% | 8.93 -> 7.47 | 0.004 | **91.8%** | 1.117 |

`anchored` 的显式 KL 基本保持了 teacher 分布，但它的配对指标并不最低，说明这些代理量
不能单独预测面板强弱。`full_lowlr` 的 pair KL 低于 `full`，面板反而明确退化；
`full` 的排序变化很大，面板却没有相对 warmup 明确退化。规则学习与策略保留必须继续
分开判断。

按 teacher 已执行动作分组后，受损不是单一动作造成。`full` 的 tied 动作 top1 为
Card 28.3%、Tune 23.0%、Switch 55.6%、Skill 80.7%、Reroll 91.9%；`full_lowlr`
相近，Card 31.7%、Tune 23.8%、Switch 65.2%。`anchored` 对应恢复到 Card 91.7%、
Tune 90.5%、Switch 85.2%。配对参数覆盖全部 15 种参数，没有发现单个参数、角色、
字段或 rule variant 足以解释整体退化。

### 梯度几何

| 臂 | paired norm | imitation norm | imitation / paired | cosine |
|---|---:|---:|---:|---:|
| `warmup` | 0.14517 | 0.00806 | 0.0555 | -0.1306 |
| `full` | 0.02695 | 0.05117 | 1.8990 | +0.1967 |
| `full_lowlr` | 0.01732 | 0.01929 | 1.1141 | +0.0841 |
| `replay` | 0.17940 | 0.01137 | 0.0634 | +0.1154 |
| `anchored` | 0.07751 | 0.00658 | 0.0849 | -0.0158 |

warmup 上的配对梯度远大于模仿梯度；训练后 `full` 和 `full_lowlr` 的配对监督已经进入
模仿梯度同一量级，`full` 甚至更强。`anchored` 的净配对梯度比例接近 warmup，但平均
参数漂移仍与 `full` 相似；门控只能解释一部分保护效果。

### 已证实的机制

1. `rule_auxiliary.RuleHead` 直接消费共享的 `state` 和 `actions`，没有 `detach`。
   配对回归本身只进入 rule head 和共享表征，不经过 Q head。
2. `full`、`full_lowlr` 和 `probe_then_finetune` 的 Q head 参数更新严格为 `0`，
   但策略排序仍改变。退化来自共享 `state/actions` 表征变化，再由固定 Q head 放大为
   新的动作排序。
3. `full_lowlr` 的 Q head 同样未更新，面板仍从 30.00% 降到 19.55%。这不是 Q head
   过拟合，也不能归因于单一高学习率。
4. `frozen` 的共享参数逐元素为零，策略完全不变，但规则泛化失败。因此只对
   `state/actions` 做 `detach`，很可能退化为不可接受的冻结方案。
5. 面板退化不是超时-only、单席位-only、单规则类型-only 或单场景-only。

因此，当前最可信的主因是纯配对后果回归持续改写共享 Q 表征；规则头和 Q head 的容量
或单独学习率都不是首要解释。`anchored` 是有效的显式保护机制，但没有证明优于 `full`。

凯亚反事实探针结果：

| 模型 | 结算预测 | 两技能策略排名 | 选择伤害领先技能 |
|---|---:|---:|---:|
| `full` | 16/16 | 16/16 | 0/16 |
| `anchored` | 16/16 | 8/16 | 0/16 |
| `replay` | 16/16 | 8/16 | 0/16 |
| `frozen` | 8/16 | 8/16 | 0/16 |
| `probe_then_finetune` | 8/16 | 8/16 | 0/16 |
| `full_lowlr` | 8/16 | 8/16 | 0/16 |

`full` 在这个受限探针上预测和策略排名都正确，但 16 例不能替代完整对局，也不能单独
通过 G1。所有臂都没有选择伤害领先技能，说明该探针仍未解释完整动作偏好。

## 未决项与下一步

- 从 `artifacts/202609160202_000021_retention_full/full_policy.pt` 进入下一轮等预算 RL；
  保留 warmup 和 `full_lowlr` 或 `replay` 的本轮结果作为退化复现参考。
- `isolated_rule` 已完成并否决：零漂移成功，但规则方向学习失败。没有同容量 control，
  因而独立路径收益与容量因素未严格分离；该限制不改变否决结论。
- 仅把 `state/actions.detach()` 作为全部修复没有足够依据，现有 `frozen` 结果已经给出
  规则学习失败的对照。`anchored` 可保留为保守回退，但不能以点估计领先宣称取代 `full`。
- 本轮只有一个训练 seed。若要再次比较 `anchored` 与 `full`，使用新的独立训练和确认 seed，
  不重用 `96600`。
- 当前结果证明 `full` 在这份配对监督中保留了已验证的策略水平并使规则学习通过，尚未证明
  对 D2 有收益，也没有证明 `anchored` 对未来 RL 更有价值。
- 训练是重量级操作。启动前先同步代码到 56，再按单个任务串行执行；本报告不触发新训练。
