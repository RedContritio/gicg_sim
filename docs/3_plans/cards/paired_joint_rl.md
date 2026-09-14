# 配对预训练后的持续监督RL

2026-09-14，用户授权立即启动。56冻结来源7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1；本机新schema尚未同步。本轮与本机集成验收独立。

## 已启动

- 入口`tools.experiments.semantic_training.paired_rl`，输出`artifacts/native_paired_rl_20260914`。
- 初始模型`artifacts/native_paired_20260914/paired.pt`；配对数据同目录`pairs.pt`。来源为上一轮已完成的360对实验，已逐对检查除hook_ir外所有观察相同。父模型/数据/config/catalog的实际文件SHA写入本轮status。
- 配对诊断格式显式导出为同来源的semantic policy容器：先严格验证provenance、state_dict及辅助头；权重和来源指纹不变。在56旧runtime中导出1.0.0，在对应新版runtime可导出2.0.0；绝不把旧权重重标新版。
- 首个正式run `D:/gicg_native/artifacts/202609141059_000032_semantic_rl`。启动确认时辅助分支第1轮已采集39/512局。
- 单个执行等待器session80476保持SSH连接，进程完成后拉取completion和比较报告。不反复轮询。新会话不可因旧句柄不可用重复启动；先查远端status/completion和进程。

## 预先固定的预算与训练

双臂顺序执行：auxiliary后control，各4轮×512局，16 workers，共4096训练局；同起点和master seed95100。五角色3v3随机合法30张、50%原生/50%训练规则变体，对手D2。先启动实际训练，不把全量基线评估放在采集前。

沿用terminal clipped policy gradient、state baseline、temperature0.5、lr1e-5、epochs2、KL/entropy限制。配对分支每个minibatch另取8对train样本，按参数均匀采样，独立Python RNG seed95103；绝对+差值+0.1全字段回归乘联合系数0.5。control不加此损失。两臂对局预算相同，额外GPU成本据实报告。

仅配对数据split=train参与更新，states/values仅事后评估。当前配对库为合成伤害/治疗局面，尚未实现对真实对局的配对刷新。保留整局胜负奖励，不以即时伤害强制策略排名。旧采集器rule_stride设为10亿，仅首个决策偶有旧结算标签，这些标签不参与配对callback损失。

checkpoint保存协议名、配对数据SHA、独立RNG状态、callback calls及批大小。calls含早停前计算过但未更新的调用，不等于optimizer updates。此入口没有resume参数；基础RL resume会因协议算法名不同拒绝，不能宣称本轮已有完整续训恢复。

## 评估

每轮原生开发seed95190，55场景×2席位×2布局220局。两臂训练后用独立变体开发95200、55场景选择候选（包含初始模型，平分选最早）。95300独立复核110场景×2席位×2布局440局/模型。保存相对初始和双臂的场景聚类配对置信区间。

初始、各分支最终及所选模型做配对预测保持检查；control用原先固定辅助头检查共享表示变化。策略规则响应探针后续另行复测，不以预测误差直接宣称强度提升。既有最终验收种子未使用。

## 验证与限制

56冒烟：4局真实原生/变体对战、双臂GPU更新，10.94秒成功；本机已有RL/辅助回归8项通过。独立agent继续审查callback和训练集隔离。

历史pairs.pt没有内嵌provenance；此次来源通过同一已完成实验的路径、完整匹配审计及本轮记录的文件SHA核对，仍需给后续通用数据接口补齐独立来源验证。不能据此任意替换同名数据文件。现有全部输入和冻结网络在正式运行期间不修改。
