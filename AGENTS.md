# 项目协作规范

## 基本约束

- `AGENTS.md` 必须始终保留在仓库根目录。
- 开始工作前先检查 `git status --short --branch`，不得重置或覆盖其他会话的改动。
- 所有命令从仓库根目录执行；Rust 使用 workspace 级 `cargo` 命令，Python 使用 `python -m <模块>`。
- 非预期输入直接失败，不维护旧 API、旧配置、旧 checkpoint 或旧目录兼容层。
- 随机数、序列化、协议、配置解析、网络服务等通用能力使用成熟依赖，不在项目内重复实现。
- 代码应直接呈现最终结构，不保留迁移垫片、临时说明或改动痕迹。

## 目标结构

```text
data/          游戏规则与牌表
gicg_engine/   Rust 规则执行器
gicg_env/      Python 绑定与环境
gicg_ai/       轻量训练框架、算法、模型与评测
web/           PvE 决策辅助界面
configs/       train / eval / web 完整配置
```

- 规则只存在于 `data/`，Python 不复制游戏逻辑。
- 通用训练框架只拥有配置、运行生命周期、产物和评测。
- 算法接口只包含初始化、采集和更新；模型、buffer、loss 与 rollout 属于算法内部。
- `tools/` 只放一次性维护命令，不承载产品或训练逻辑。

## 测试范围

- 测试只覆盖规则结果、跨语言边界、训练闭环、评测统计和 Web 主流程。
- 不测试内部拆分、导入路径、兼容别名、历史入口或输入校验。
- 单个函数的圈复杂度不得超过 10；Rust、Python、JavaScript 和 Lua 统一由 Lizard 检查，Python 同时启用 Ruff `C901`。

## 配置与产物

- 配置位于 `configs/{train,eval,web}/`，每个 TOML 必须完整且可独立运行，不使用继承。
- 机器信息只写入 gitignored 的 `configs/hosts.toml`。
- 运行产物位于 `artifacts/<experiment_tag>/<时间戳>_<六位序号>/`，包含配置、metadata、checkpoint 和指标。

## 验证与提交

- 验证范围与风险匹配；Rust 优先运行 `cargo test --workspace` 与 `cargo clippy --workspace --all-targets -- -D warnings`。
- `pre-commit` 只执行快速、只读的格式、静态分析、复杂度和仓库卫生检查；完整测试放在 `pre-push`。
- hook 缺少依赖时必须直接失败并给出安装命令，不得联网安装、静默跳过或自动修改文件。
- 提交信息准确描述交付结果，不描述中间过程。

## 用户可见内容

- UI、报告、截图和导出文件只写产品内容，不写实现理由、调试过程或下一步计划。
- 设计说明、限制与取舍只写在开发文档或聊天回复中，除非用户明确要求展示。
