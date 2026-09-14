# 合入 main 前的推理一致性修复

2026-09-14，用户授权 sol/high 子agent处理三项提交回归。此前新建曾报线程上限，但本次已成功恢复fix_rule_graph_paths，并新建sol/high的mirror_fix_parallel与web_loader_parallel。三项现已完成集成验收；未修改56冻结训练目录。此前不能并行的解释不作为当前事实。

## 1. 规则关联贯通

canonical hook去掉任意卡牌ID后，旧DMC未携带效果关联，导致调和不同卡牌的同骰色动作混同。不能靠重新加入ID修复。

引擎静态观察必须携带定义关联，Go/Python采样、经验存储、batch、单步、provider/server共享解释。共享ActorCritic及其他受影响范式需消费关联，SemanticQNet不能重复聚合。静态容量要有显式溢出保护；排列后引用要重映射。验证真实不同效果卡牌可区分、相同输入各路径一致、梯度可达效果编码。

该改动属于输入/结构兼容性变化，不给旧权重重标指纹；56当前实验仍在其冻结源码上有效运行，不能拿本地新版直接重评旧权重。

## 2. 镜像信号测试

旧测试把policy约2e-6的变化用atol1e-5判为“相同”。改成受控typed输入干预和梯度通路检查，证明视角信息到达policy；不是放松测试使任何网络都通过。

## 3. 网页回归统一加载入口

普通网页对手已经用training.core.matchup.loaders.load_player。semantic_live是临时实验旁路，硬编码semantic_duo配置与旧iteration7路径，还固定两角色阵容，导致模型/规则/前端不同步。

统一入口应负责按模型类型创建适配器、严格加载来源兼容的checkpoint、初始化每局独立状态。网页负责会话和渲染，不自行复制模型初始化；评估入口与网页使用同一semantic装载逻辑。避免core向tools反向import，可由组合入口显式注册实验适配器。

服务配置负责选择模型、训练规则配置与匹配的评估资料，前端从profile读取队伍规模/重叠规则。模型未安装或不兼容时明确不可用，不拿随机权重当已训练模型。保留路径白名单与来源指纹守卫。测试使用临时兼容fixture，不依赖机器上恰好存在的历史训练产物。

## 合并条件

三项定向测试及受影响多范式/推理端到端检查通过；重新跑提交时失败项与共享层回归；文档解释兼容性变化。修复完成后再决定main快进，不因研究胜率未过50%而无限推迟代码合并，也不以研究尚未完成为理由忽略工程回归。

## 实现结果

规则关联现在位于固定静态观察尾段，格式为 `schema_version, count, (source_hook, effect_hook)*capacity`。Go 端合并 skill 与 card hook 关系后排序、去重，并在超过 16384 条时直接失败；shuffle 后写入的是重映射索引。Python 在解析前校验静态观察精确长度、schema、整数 count、容量和 hook 索引。DMC 的采样、经验组装、batch、单步/provider 推理以及 AZ、PPO、BC、CFR 都携带并消费该关系；SemanticQNet 复用同一个 `DefinitionRelation`，不会重复聚合。

DMC checkpoint schema 从 2 升到 3，semantic checkpoint 格式从 `semantic-q/1.0.0` 升到 `semantic-q/2.0.0`。旧权重不重标、不静默补默认关系；源码指纹、格式或规则配置不匹配时拒绝加载。

实验诊断导出是单独的兼容路径：`paired_replay.export_initial`在严格校验来源指纹与网络结构后，保留父模型对应的semantic格式。56冻结旧runtime可导出1.0.0；这不是让本机新版网页loader接受旧模型，也不重标指纹。

镜像测试改为受控 typed 输入干预，并检查 policy 信号和可反传梯度。网页 semantic 对手通过可注册 loader 与评估入口共享装载和选动作逻辑；服务配置选择 config、checkpoint 与评估报告。队伍规模和阵容约束来自 config。模型缺失、旧格式或 provenance 不匹配时 profile 明确标记不可用，不创建伪装成训练模型的随机权重。

## 2026-09-14 验收证据

- `go test ./gicg_engine/...`：全部通过，包含 observation shuffle、schema 与固定尺寸测试。
- Python 训练套件（排除另行执行的 `smoke_full`）：1150 passed、6 skipped、10 deselected。
- 原失败与共享网络定向集：51 passed，覆盖 tune action logits、mirror、definition relation、静态布局、DMC batch、AZ、CFR 与共享网络模块。
- semantic 训练与网页后端组合：82 passed；覆盖网页和评估选择同一动作、两会话隔离、缺失模型、错误 provenance 与旧格式拒绝。
- 默认 smoke：5 passed。全范式 `smoke_full` 首轮 9 passed；当时唯一 DMC resume 失败是并行修改符号链接源码导致首训与续训指纹不同。源码稳定后单独重跑 DMC 的首训、checkpoint、严格加载和续训，1 passed（505.53 秒），因此五个范式均有通过结果。
- 变更文件 `ruff` 定向检查、`compileall`、`gofmt -d`、`git diff --check` 和 OpenSpec 索引检查通过；生产文件不超过 300 行，测试文件不超过 500 行。
- 前端 `npm run build` 通过。全仓前端 lint 仍报告两个既存的 `react-hooks/set-state-in-effect`：`CheckpointPicker.tsx:38` 与 `Replay.tsx:32`，均不在本次改动内。
