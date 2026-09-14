---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
---

# `docs/paradigms/` — Paradigm dossier historical index

> 本目录冻结 2026-05-16 前后的 paradigm 判断，不表示 2026-09-14 的
> 活动训练状态；当前任务与运行统一看 [`../0_status/README.md`](../0_status/README.md)。
> 每 paradigm 一个子目录,记录该 paradigm
> 在 GICG 上的尝试轨迹、关键 run、ablation、postmortem、verdict。
>
> Layout 标准:
> [`openspec/specs/openspec-policy/file-layout.md`](../../openspec/specs/openspec-policy/file-layout.md)
> §3 Layout 3 — Paradigm dossier。
>
> **dossier 是"我们尝试了什么 / 学到了什么"**(实验记录)。Paradigm
> 决策(SHALL 句)落 `openspec/specs/paradigm-<name>/`(若有),不落
> 本目录。详 [`content-boundary.md`](../../openspec/specs/openspec-policy/content-boundary.md)。

## Paradigm index

| Paradigm | Status | One-line verdict |
|---|---|---|
| [`ppo/`](./ppo/) | **CLOSED** | Stage 3 F1-D2 ceiling 0.344(30+ ablation,closed by ADR-0008 paradigm pivot + ADR-0009 curriculum terminus)|
| [`az/`](./az/) | **CLOSED (partial reopen)** | Stage 3 plateau 0.10-0.27 across stacks;s068 D4 asymmetric +0.167 partial reopen via ADR-0010;s069 cancelled |
| [`cfr/`](./cfr/) | **CLOSED** | r008 Deep CFR prototype iter 199 collapse(40% vs random, 0/10 vs 一切);user-evaluated closure 扩展含 NFSP / Deep CFR redo |
| [`bc/`](./bc/) | **PRODUCTION FALLBACK** | r009 BC ckpt epoch_3 vs F1-D2 = 0.75(tied-noise reduction 让 BC argmax 超 teacher);ADR-0009 钦定 fallback |
| [`dmc/`](./dmc/) | **ACTIVE at snapshot** | Phase 3.4 smoke verified 2026-05-14;Phase 3.5 infra ship 2026-05-15;当时 Stage 3 Windows GPU train pending |

## How to use this index

1. **进入 paradigm 想了解结论** → 读 `<name>/README.md`(≤200 行 verdict + 入口导航)。
2. **想知道某 run 数据** → `<name>/runs.md` time-ordered 列表 → 跳 `python -m tools.runs.show <run_id>` 完整数据(live)OR `docs/5_history/runs_pre_redesign_2026_05_17.md`(pre-redesign 历史)。
3. **想知道某 ablation/architecture/postmortem 细节** → 子目录(`ablations.md` /
   `architecture.md` / `postmortems.md`)+ cross-ref 到 `docs/5_history/` 已有复盘。
4. **想找 paradigm 决策(为什么 closed / pivot)** → ADR via
   `openspec/changes/archive/<NNNN>-*/`,列在每个 paradigm README 的
   "Cross-references" 段。

## Conventions

- 每 paradigm dossier 至少有 `README.md` + `runs.md`。
- Postmortem / ablation / architecture 子文件**不复制**已有
  `docs/5_history/` 内容,只 link;dossier 给 paradigm-level 概览。
- 行数遵 [`thresholds.md`](../../openspec/specs/openspec-policy/thresholds.md)
  表 1 `docs/paradigms/**/*.md` 行(≤500),README 走 Layout 3 §3.1
  特殊约束 ≤200。
- LIVE working notes(如 `training/paradigms/dmc/notes.md`)只 link,不复制。
- 已废 epoch 的代码层归档在
  [`docs/5_history/eras/`](../5_history/eras/)(如 `ppo_pre_az/`);
  dossier 引用 era 而非吞并。

## Cross-references

- OpenSpec layout spec:
  [`openspec/specs/openspec-policy/file-layout.md`](../../openspec/specs/openspec-policy/file-layout.md)
  §3 Layout 3
- Line/byte thresholds:
  [`openspec/specs/openspec-policy/thresholds.md`](../../openspec/specs/openspec-policy/thresholds.md)
- Run registry: `python -m tools.runs.list` CLI(live);pre-redesign archive [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../5_history/runs_pre_redesign_2026_05_17.md)
- Frozen history: [`docs/5_history/`](../5_history/)
- Archived OpenSpec changes:
  [`openspec/changes/archive/`](../../openspec/changes/archive/)
