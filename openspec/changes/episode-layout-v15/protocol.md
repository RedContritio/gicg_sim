# v15：每局观测排列小预算试验

2026-09-12，用户授权“加上这个试试”。

serial DMC 每局重建环境，用 master + episode_seq 派生 layout、episode、deck_0、deck_1 四条种子流。
原 cheap reset 保持排列；factory 增加可选 layout_seed，旧三参数构造入口兼容。
每局 game_start 重建双方 NN 静态输入；原生工厂重建 Python 静态缓存、归一化与遮罩。
异步及其他范式不在本轮迁移范围，不宣称已有同样覆盖。
评估每个 scenario 一个独立布局，两侧及两类对手共享该布局；配对区间按 scenario 重采样。

## 预算与判据（运行前固定）

configs/dmc/pre_rl_small.toml；41/42/43 各 3000 agent frames，完整终局允许超出少量。
全部随机初始化；不加载 v14 权重。模型、奖励、探索率、对手混合不变。
新最终评估 master108000，每对手32个scenario×两侧=64局；随机基线、三初始化、三最终，共896局。
107000仅测试使用。按预算末尾选模型，不按最终分数选检查点。
主判据：三种子对随机 score >0.5；相对各自初始化的 F1-D2 平均改善 >=0.05，最多一个种子退步。
报告逐局结果及配对 bootstrap95%区间，有限样本通过不等于显著性或长程稳定性。
不以历史不同评估集的分数作 shuffle 的因果提升；本轮还拆分牌库种子，若需归因另做同源固定布局对照。
未通过则记录失败并停止自动加预算，不扩到2v2/5070Ti。

## 验证

布局独立性/原始轨迹一致/缓存刷新/连续与断点恢复/工厂兼容/终局完整性：21 passed。
五范式默认 smoke：5 passed。无网络结构或配置schema改动，不重跑完整长程smoke。
v14完整前置验收为历史证据；本变更不改DSL/Go/NN结构，不复制其辅助训练结果冒充v15重跑。
本版本显式检查：python -m tools.cards.rule_baseline --manifest openspec/changes/episode-layout-v15/source-manifest.json。
旧 tools.experiments.pre_rl 固定v14，不适用于此实验；不重写旧manifest。
