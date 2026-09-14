# 设计

## 异步统计的所有权

EpisodeRunner 依据 EpisodeSpec.scenario_seed 创建对局，并将其写入 EpisodeRecord。
DMCMultiProcessCollector 只消费记录和分配本地统计序号，因此记录中的 scenario_seed
是该路径唯一可直接证明的对局种子。汇总顺序不可替代 actor 的随机流信息。
保留 serial 已有的四路 seeds 字典；不伪造异步尚未传递的 layout/deck 种子。

## 职责拆分

Go 同包函数移动至按职责命名的文件，保留导出名、C export 标记和方法体。
Python 的环境、网络已有组合式结构，抽出状态/观测/批量前向 mixin，
原类继续提供同名方法；decoder 保留原入口的显式重导出。
不改变 nn.Module 注册、参数键、观测布局、动作含义或规则执行顺序。
搬移内容用 AST 等价核对，并由真实引擎、NN 和恢复测试验证连接方式。

## 验证与来源

修复异步 NameError 是有意的行为变更；其余生产改动是结构调整。
文件路径和内容属于严格来源指纹，因此结构等价不意味着旧 checkpoint 可直接加载。
旧来源及源码归档保持不变；新版本单独冻结。旧训练继续使用对应旧源码，
不添加兼容绕过，不修改旧权重中的来源元数据。
