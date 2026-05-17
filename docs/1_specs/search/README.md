# 1_specs/search/ — 搜索算法 (DEPRECATED, P1-T3 moved to OpenSpec)

> **2026-05-15（P1-T3）**:本目录三文件已迁到 OpenSpec。新规约（SHALL 语言）位于:
> - [`openspec/specs/search-ismcts/`](../../../openspec/specs/search-ismcts/spec.md) — IS-MCTS 算法 + 确定化采样
> - [`openspec/specs/search-parallel/`](../../../openspec/specs/search-parallel/spec.md) — 并行推理 + 异步训练流水
>
> 实测性能 / MPS GPU 失败 / 耗时估算 → [`docs/5_history/search_history.md`](../../5_history/search_history.md)
>
> 本目录文件保留至 P1++ 整体清理；**只读**。

| 文件 | 用途（历史） |
|---|---|
| [`is_mcts.md`](is_mcts.md) | IS-UCT 单树, N_avail, PUCT, lambda 混合 leaf eval |
| [`determinization.md`](determinization.md) | 隐藏状态采样 (CardPoolSpec / dice 颜色) |
| [`parallel.md`](parallel.md) | 推理服务器 + 虚损失并行 rollout |

ADR: `../../2_decisions/` 里的 IS-MCTS / determinization / ExpandUnionK 系列 + `openspec/changes/archive/0004-is-mcts-migration/`。
