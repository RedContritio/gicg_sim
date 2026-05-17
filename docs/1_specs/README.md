# 1_specs/ — Shipped 代码状态快照

> 反映**当前 shipped 代码**。LIVE,代码改了就改 doc。
>
> 与 `2_decisions/` 区别:specs 写"现在长什么样",decisions 写"为什么是这样"。
> 与 `3_plans/` 区别:specs 是 shipped 的,plans 是计划中的。

## 子系统

| 目录 | 子系统 | 关键 doc |
|---|---|---|
| [`engine/`](engine/) | Go 引擎 + Lua DSL + capi | actions / capi_mirror / dsl/{api,conventions,structure} / dice |
| [`env/`](env/) | gicg_env Python 层 (obs / action / reward / scenario) | (待写,从 az/specs 拆) |
| [`network/`](network/) | AZ ActorCritic 网络架构 | current (5d state_vec, struct_readout, sid pinning) |
| [`search/`](search/) | IS-MCTS / determinization / parallel inference | is_mcts / determinization / parallel |
| [`training/`](training/) | training/ 三层 (framework / az / cfr / ppo) | layout / az_loop / implementation |
| [`eval/`](eval/) | gauntlet / eval_service / arena / matchup | (待写,从代码沉淀) |

## 编辑规则

- 代码改了**同 commit 内**改 spec
- 过时段落 **直接改**,不留 tombstone (与 history/ 区分)
- 跨 spec 引用用相对路径 `../search/is_mcts.md`
- 引用决策用 `../../2_decisions/adr-NNNN-*.md`
