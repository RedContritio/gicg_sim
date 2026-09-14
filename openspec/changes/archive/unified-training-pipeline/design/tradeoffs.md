---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Tradeoffs — 关键决策的选项对比

> 列出本设计中遇到的关键 tradeoff,每项标 选项 / 选择 / 理由 / 反对意
> 见。用于后续 review / archive retrospective 回溯。

## 1. T-A — `framework/` 删除 vs 保留

**选项**:
- (A) 删除 `training/framework/`,内容融入 `core/`
- (B) 保留 `framework/`,paradigm 仍 import framework

**选择**:**A**(D3 决策)

**理由**:
- (A) 消除"framework + 5 stack"双层 mental model
- (A) 修复 ADR-0006 隔离违反(framework import paradigm-specific)
- (A) 单一 paradigm-agnostic layer 与 5 paradigm-specific layer 边界清晰

**反对意见**:
- (B) 短期 P3 工作量小(不用 mv 80 文件)
- (B) `framework/` 名称在 docs / memory 中已使用频繁

**反驳**:P3-P5 一次性付 mv 成本换永久 mental model 简化,合算;`framework`
关键字 grep 替换可机械化。

## 2. T-B — Local vs Remote inference 默认

**选项**:
- (A) 默认 Local(每 actor 持 model copy)
- (B) 默认 Remote(K 个 inference server)

**选择**:**A**(default local)

**理由**:
- GICG 当前 ~5M params,model copy RAM cost 可接受(20 MB per actor)
- Local + CPU 配置最简单,smoke + debug 快
- Remote 适合 GPU batching,但 GICG 当前 obs 维度 batching gain < 2x

**反对意见**:
- (B) 大模型(若未来 >50M params)RAM 不够
- (B) GPU 利用率高

**反驳**:NetworkProvider 抽象保证 cfg 一行切换 placement,默认 local 不阻
塞未来切 remote。

## 3. T-C — EpisodeRunner 共享 vs 分裂

**选项**:
- (A) 1 个 EpisodeRunner + N EpisodePolicy(本 change 选择)
- (B) 每 paradigm 1 个 Runner(当前现状)
- (C) Driver 直接 inline episode loop

**选择**:**A**

**理由**:
- (A) Bug fix(如 #152 mirror)只改一处
- (A) Determinism 测试 surface 收敛(1 个 runner × 5 policy)
- (A) Actor + eval 100% 共享(SHALL #5)

**反对意见**:
- (B) Paradigm 实施 freedom 高(可 paradigm-specific runner 优化)
- (C) Driver 端可见 episode flow,debugger 友好

**反驳**:
- (B) 优化空间通过 Policy 内部实现就足够(MCTSPolicy 内做 tree reuse 等)
- (C) Driver 主循环已经够复杂,不应再 inline runner

## 4. T-D — Serial vs Async 选项(per paradigm)

**选项**:
- (A) 每 paradigm 自定 serial / async(本 change)
- (B) 全 async(高吞吐)
- (C) 全 serial(简单)

**选择**:**A**(cfg `pipeline.mode` 由 paradigm preset 决定)

**理由**:
- CFR traversal 性质决定 multi-actor 收益小 → serial 合理
- DMC / AZ async 必需(achieve N × 8-actor sample rate)
- BC 无 env episode → mode 字段 N/A

## 5. T-E — BC first-class vs 嵌入 AZ

**选项**:
- (A) BC 独立 `paradigms/bc/`(D1)
- (B) BC 留在 `az/bc_*.py`(当前)

**选择**:**A**

**理由**:
- r009 production fallback ckpt 维护需独立 lifecycle
- AZ + PPO 各自重复实现 BC(~600 LOC dup)
- BC 是 RL warm-start 通用 prior,跨 paradigm 共享

**反对意见**:
- (B) BC 实质是 supervised loss + dataset,不符合 Collector + Buffer +
  Loss "RL paradigm" pattern

**反驳**:6 protocol 设计已经为 BC 留 hook(`requires_network_in_collect=False`),
形式化 BC 为 paradigm 成本低。

## 6. T-F — PPO 迁移 vs archive

**选项**:
- (A) 迁 `paradigms/ppo/`,保留 smoke 可重现性(D2)
- (B) Archive 只留 docs,代码删除

**选择**:**A**

**理由**:
- 跨 paradigm lever 验证 PPO 是 fast baseline(2026-04 ablation 用过)
- Reimplement 成本 > 1-2 days 迁移成本
- PPO frozen tier 不接受 new run,但保留 reproducible smoke

**反对意见**:
- (B) Code 不删长期 rot;后续维护 5 paradigm 比 4 paradigm 累

**反驳**:Tier `frozen` 显式不维护,只跑 smoke;rot 限于 cfg / dep drift,
不阻塞主路径。

## 7. T-G — Cfg INHERITED_FIELDS extensible vs hardcode

**选项**:
- (A) Registry-driven `INHERITED_FIELDS` dict(本 change)
- (B) Hardcode device / seed 两个字段
- (C) 全字段都允许继承(高自由度)

**选择**:**A**

**理由**:
- Hardcode 阻塞未来加 `dtype` / `log_level` / `checkpoint_root` 等(thresholds.md §6.2)
- Registry 可在加新字段时同步 spec(thresholds + cfg-schema)
- 全字段继承 → cfg 文件读起来 ambiguous(哪个字段 inherit 哪个不?)

## 8. T-H — Old tools 直接删 vs 合并分类

**选项**:
- (A) `git mv` + adapter 化(D5)
- (B) 删除 + 重写

**选择**:**A**

**理由**:
- 历史价值(部分 tools 有 ad-hoc fixes / domain knowledge)
- git mv 保留 blame 历史 + diff 评审低成本
- adapter 化把 `--az-ckpt` → `--ckpt` cost < reimplement

**反对意见**:
- (B) 老 tool 部分代码 ugly,留下技术债

**反驳**:P5 期间允许 cleanup commit,但默认 git mv 优先。

## 9. T-I — Subdir spec.md vs single spec.md(per paradigm)

**选项**:
- (A) 每 paradigm 主 spec.md + subtopic(若需要)
- (B) 每 paradigm 单文件 spec.md

**选择**:**B**(本 change 5 paradigm spec 都是单文件)

**理由**:
- 每 paradigm 初版 ~10-15 SHALL,< 300 行
- Paradigm 细节(实施 note / run history)留 `docs/paradigms/<name>/notes.md`
- 后续若 paradigm spec 增长可拆 subtopic(后拆原则,thresholds.md §6.2)

## 10. T-J — Tools subdir vs flat(P5)

**选项**:
- (A) 子目录分类(eval / debug / probe / ...)
- (B) Flat `tools/*.py`(当前)

**选择**:**A**(本 change tools-layout/spec.md)

**理由**:
- Flat 当前 ~40 个文件,可读性差
- Subdir 按功能分组,新工具明确归属
- `python -m tools.<sub>.<name>` 与 CLAUDE.md 现有约定兼容

## 11. Cross-references

- 决策起点 → [`../proposal.md`](../proposal.md)
- 历史 ADR-0006(training layout)→ [`../../0006-training-layout/`](../../0006-training-layout/)
- DMC review(41 critique 含部分 tradeoff)→
  `docs/5_history/reviews/dmc_review.md`
- Memory:训练 layout history → `memory project_training_layout`
- Memory:RL closure → `memory project_rl_closure_2026_04_28`
