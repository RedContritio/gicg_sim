# 4_runs/ — Run lifecycle 入口与历史单 run 资料

> 2026-05-18 起不再维护 Markdown run 注册表；live 索引来自每个 artifacts 目录的 `metadata.toml`。
>
> 区别:
> - 这里只有"哪个 run 跑了什么":registry + 个别 run 的 plan/result
> - **完整 postmortem** 写到 `5_history/postmortems/`
> - **ablation 量化矩阵** 写到 `5_history/ablations/`

## 内容

| 文件 | 用途 |
|---|---|
| `python -m tools.runs.list` | 扫描 `artifacts/*/metadata.toml` 的 live 表格视图 |
| `python -m tools.runs.show <NNN>` | 显示单 run metadata 与版本化配置快照 |
| [`_individual/`](_individual/) | pre-redesign 单 run 的 plan / detailed result |

## 命名 (与 artifacts/ 对齐)

新式目录为 `artifacts/YYYYMMDDHHMM_<NNNNNN>_<slug>/`，时间戳为 UTC，序号为六位十进制。
`python -m tools.runs.train <cfg>` 原子完成编号分配、配置快照、训练与 metadata 收尾。
Pre-redesign 的 `rNNN` / `sNNN` 记录保存在 [`../5_history/runs_pre_redesign_2026_05_17.md`](../5_history/runs_pre_redesign_2026_05_17.md)。

## 编辑规则

- 运行训练只用 `tools.runs.train`，不要手建编号或 metadata。
- 外部死亡用 `tools.runs.mark` 收尾；metadata 丢失用 `tools.runs.recover`。
- 失败 run 的 artifacts 目录保留；复盘写入 `5_history/postmortems/`。
