# 4_runs/ — Run 索引与单 run 详情

> 训练 / smoke / bench run 的注册表。
>
> 区别:
> - 这里只有"哪个 run 跑了什么":registry + 个别 run 的 plan/result
> - **完整 postmortem** 写到 `5_history/postmortems/`
> - **ablation 量化矩阵** 写到 `5_history/ablations/`

## 内容

| 文件 | 用途 |
|---|---|
| [`registry.md`](registry.md) | LIVE,所有 r/s 的权威 index,新 run 必须 pre-register |
| [`_individual/`](_individual/) | 单 run 的 plan / detailed result(只放需要长保留的) |

## 命名 (与 artifacts/ 对齐)

`artifacts/YYYYMMDDHHMM_<label>/` where `<label> = <type><NNN>_<slug>`

- `r` — production-style run
- `s` — smoke / validation / bench

详见 [`registry.md`](registry.md) Process 段。

## 编辑规则

- 启动 run 前先 register (status `pending`)
- run 结束后填 result + 翻 status
- 失败的 run **不删 row**,标 `failed` 或 `superseded`
- 单 run 的复盘 ≥ 1 页时,在 `5_history/postmortems/` 开新 doc
