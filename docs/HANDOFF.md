# 接手说明

更新时间：2026-09-24

## 当前基线

- 分支：`dev`
- 版本：`v0.4.1`
- 正式模型：`artifacts/dmc_central/20260923_191033_000001/checkpoint.pt`
- Web 配置：监听 `0.0.0.0:51731`，产物根目录为 `artifacts/`
- 当前服务入口：`http://127.0.0.1:51731/`
- 当前报告入口：`http://127.0.0.1:51731/reports`

## 版本内容

`v0.4.1` 包含评测报告及 M1 数据链路：

- `python/gicg_ai/evaluate.py`：逐局记录剩余生命、存活数和 M1，输出平均 M1 与 JSON。
- `web/app.py`：按运行聚合评测索引，并提供包含该运行全部对手的在线报告页。
- `web/static/reports.*`、`web/static/report.*`：历史列表与 ECharts 在线报告。
- `web/static/nav.css` 及各页面：统一全局导航。
- `package.json`、`package-lock.json`：增加 ECharts 和 simple-statistics。
- `configs/web/local.toml`：改为 `0.0.0.0:51731` 并配置产物目录。
- `README.md`、`AGENTS.md`、`docs/`：同步当前状态与文档入口。

生成的 `artifacts/` 文件不纳入 Git。当前新增评测：

```text
artifacts/dmc_central/20260923_191033_000001/eval_vs_f1d2_mps.json
```

## 已完成验证

- Ruff、Biome 和 Lizard 已通过，函数圈复杂度不超过 10。
- Python 相关测试通过。
- 报告路由以运行目录为标识，详情页同时呈现该运行下的全部评测和对手。
- 总评表合并换边结果，每次评测占一行；胜率与分子/分母分层呈现，全零列不显示，平局和截断的非零值标红，M1 分布单独呈现。
- M1 图表在节点挂载后初始化；均值与四分位数显示在图表右下角，不再显示分布明细。
- Web 服务通过本机 HTTP 验证；当前 13 份评测聚合为 6 份运行报告。
- `dmc/20260923_165604_000001` 报告包含 5 次评测、4 个对手和 4,020 局。
- MPS 复评完成 1,000 局：788 胜、212 负、无平局、无截断，平均 M1 为 9.024。
- 换边后的 500 组分为：先手必胜 86、后手必胜 84、DMC 必胜 309、F1D2 必胜 21；
  M1 的 Q1、Q2、Q3 为 6、9、11，均值为 9.024。
- MPS 复评耗时 271.50 秒；当前串行 F1D2 评测不应默认优先 MPS。

提交前检查已通过。

## 运行命令

启动 Web：

```bash
.venv/bin/python -m web --config configs/web/local.toml
```

本地 CPU 评测：

```bash
.venv/bin/python -m gicg_ai.evaluate configs/eval/dmc_vs_f1d2.toml \
  --candidate-checkpoint artifacts/dmc_central/20260923_191033_000001/checkpoint.pt \
  --output artifacts/dmc_central/20260923_191033_000001/eval_vs_f1d2_cpu.json \
  --set evaluation.device=cpu
```

MPS 只在需要设备对照时显式启用：

```bash
.venv/bin/python -m gicg_ai.evaluate configs/eval/dmc_vs_f1d2.toml \
  --candidate-checkpoint artifacts/dmc_central/20260923_191033_000001/checkpoint.pt \
  --output artifacts/dmc_central/20260923_191033_000001/eval_vs_f1d2_mps.json \
  --set evaluation.device=mps
```

## 当前会话约束

- 禁止使用远端 `gpu56`，包括唤醒、状态查询、同步、训练和评测。
- 不打开浏览器或页面；界面验证只使用代码、测试和 HTTP 请求。
- 不恢复 OpenSpec。架构约束以 `AGENTS.md` 为准，当前事实以本目录文档为准。
- 提交或推送前先取得用户明确指令；不得覆盖工作区中的现有改动。

## 下一接手动作

从新评测结果定位候选模型在高 M1 败局中的共同状态，并确定困难样本策略。
