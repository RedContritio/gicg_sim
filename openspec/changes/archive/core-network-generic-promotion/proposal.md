# core/network/ 通用化提升 + cfg/registry 重设计

**Status:** Active change (proposal)
**Date opened:** 2026-05-17
**Supersedes:** None(`archive/az-paradigm-rewrite` 收尾后顺延)
**Affected specs:**
- `network-architecture/spec.md`(MODIFY 多条 SHALL invariant)
- `config-schema/spec.md`(MODIFY 增 `ObsShape` + `ParadigmConfigBase` + `version`)
- `training-architecture/{spec,network-sharing,paradigm-onboarding}.md`(MODIFY smoke 契约 + generic primitives)
- `paradigm-{az,bc,cfr,dmc,ppo}/spec.md`(MODIFY,PPO 升级最重 — 切 structural backbone)
- `tools-layout/spec.md`(ADD `tools/runs/` capability)

## Why

`archive/az-paradigm-rewrite` 完成后,5 paradigm 仍**不对称**,根本原因是 P5
unified-training-pipeline 留下的两处 transitional state:

1. **`core/network/legacy/` 命名误导**:实际是当前 production building blocks
   (`ActorCritic` 207 行 + `AgentBase` 300 行 + `trunk.py` 4 个 encoder + `typed_damage.py` 350 行 + `loss.az_losses`),被 30+ files 引用。同目录 root 已有 `CoreActorCritic` 182 行 + `encoder.py` 4 个**同名**class — 两套 ActorCritic 并存,新加 paradigm 不知该 import 哪个。
2. **r009 ckpt 兼容约束**(ADR-0009 钦定 production fallback)阻碍 ActorCritic
   彻底重设计;实情是 2026-05-08 ADR-0019 后 strict-load 已名存实亡,user 决策正式撤销。

ckpt + cfg 兼容性约束彻底解除后,可以做的事:

- **AgentBase + ActorCritic 重新设计为 first-class generic abstractions**(DI 风格,thin composition)
- **PPO 从 outlier 收编进 generic backbone**(当前 flat MLP 完全忽略 hook + counter + typed segments,不是算法约束是早期工程选择)
- **5 paradigm 真正 100% 对称**(同一 backbone + 各自 head config + 各自 loss + 各自 collector strategy)
- **cfg 层**:`ObsShape` 抽出共享,ckpt 升级为 self-describing(`paradigm/cfg_version/cfg/net_kind/state_dict/git_commit/created_at`),cfg 加 `version` 字段
- **TOML 按 paradigm 重组**:`configs/<paradigm>/{default,smoke,runs/<id>}.toml`,取代生命周期扁平结构
- **Run registry 升级**:从手维护 markdown 表格 → per-run TOML metadata(gitignored) + `tools.runs.{register,complete,list,show,sync}` CLI,跨机 sync 用 rsync 包装

## What

1. **Generic primitives 重设计**:`core/network/legacy/` 整目录消失,内容提升到
   root 并重写 — `ActorCritic` 退化成 ~80 行 thin composition(encoders +
   readout + heads + optional typed_damage 全部 DI 注入);`AgentBase` 接口改 DI
   (`hook_encoder` 构造注入,不再硬约束 `self.net.hook_encoder` attribute);删
   `az_losses` 函数(AZ 已 inline);`CoreActorCritic` 命名取消,简单叫 `ActorCritic`。
2. **5 paradigm 切到新接口 + 扁平化**:AZ/DMC import 更新;BC `legacy/` 扁平到主目录(`bc/train.py` + `bc/dataset.py` + `bc_loss` 内联);CFR `legacy/` 扁平(`cfr/agent.py` + `cfr/strategy_net.py`);PPO 重写 `network.py` + `_rollout.py` + `collector.py` + `paradigm.py`,从 flat MLP 改用 generic ActorCritic backbone。
3. **Cfg 层重设计**:抽出 `core/cfg/shape.py::ObsShape` + `core/cfg/base.py::ParadigmConfigBase`(`version` + `paradigm` + `shape`)。Paradigm config 嵌套 sub-cfg 保持。ckpt save/load 升级为 self-describing schema。
4. **TOML 按 paradigm 重组 + 历史归档**:`configs/{active,shipped,smoke,_archived}/` 全删,新 `configs/<paradigm>/{default,smoke,runs/}.toml`。git tag `pre-core-network-redesign-2026-05-17` 锚永久 history。`docs/4_runs/registry.md` 内容一次性 dump 到 `docs/5_history/runs_pre_redesign_2026_05_17.md`。
5. **Run registry 工具化**:新增 `tools/runs/{register,complete,list,show,sync}.py` CLI + `schema.py` TOML schema。Run metadata 落 `artifacts/runs/<id>.toml`(gitignored,跟 ckpt 同 lifecycle)。`tools.runs.sync pull/push <host>` 包装 rsync 跨机同步 metadata(不同步 ckpt)。
6. **每 paradigm e2e smoke**:5 paradigm 各 1 个 `≤ 2min` mini-train+eval smoke test(`test_<paradigm>_smoke.py`),验证 train pipeline alive(collector → buffer → forward → backward → optimizer.step → terminal reward 流通)+ paradigm-specific invariant(AZ MCTS visit / BC CE loss decrease / DMC Q-value finite / CFR strategy 归一 / PPO clip ratio bounded)。

## Affected specs

| Capability | Change type | 关键 SHALL 影响 |
|---|---|---|
| `network-architecture` | MODIFY | invariant 1-11 多条:generic ActorCritic + AgentBase DI + typed_damage first-class + 删 `az_losses` 跨 paradigm 共享语义 |
| `config-schema` | MODIFY | 增 `ObsShape` shared base + `ParadigmConfigBase` + `version` 字段;ckpt schema self-describing |
| `training-architecture` | MODIFY | network-sharing.md 更新 generic primitives;paradigm-onboarding.md 增 smoke 契约;protocols.md AgentBase DI |
| `paradigm-az` | MODIFY | import 路径切 root(legacy/AgentBase → AgentBase);撤销 r009 production fallback 条款 |
| `paradigm-bc` | MODIFY | import 路径切;legacy/ 扁平化到主目录;撤销 BC PPO variant 残留引用 |
| `paradigm-cfr` | MODIFY | import 路径切;legacy/ 扁平化;撤销 C6.2 r008 reproducibility 条款 |
| `paradigm-dmc` | MODIFY | import 路径切(AgentBase / ActorCritic / AgentConfig 全部 root) |
| `paradigm-ppo` | MODIFY | **重写 network/_rollout/collector/paradigm** — 从 flat MLP 改用 generic ActorCritic backbone + structural obs 流 + game_start cache pattern |
| `tools-layout` | ADD | 新 `tools/runs/` capability(CLI + schema + rsync sync wrapper) |

## Out of scope

- **PPO 性能调优 / 新 ckpt train**:本 change 只验证 smoke pass,不要求 PPO 在 structural backbone 上达到 flat MLP 的历史性能(production train 用户后续单独决策)。
- **PPO backbone 切换**(scope adjustment 2026-05-17):PPO 完整 backbone 切换(flat MLP → structural ActorCritic + 重写 obs flow + collector + buffer + rollout)从本 change 移出,defer 到独立 follow-up change `ppo-structural-backbone-migration`。理由:PPO 已 fully self-contained(0 legacy 依赖),Phase 2.6 git rm `core/network/legacy/` zero break PPO;backbone 切换 ~500-1000 LOC 是独立 sub-project,混入本 change 让 scope 失控。Spec invariant "5 paradigm 共用 backbone" 仍是 follow-up TODO。
- **新 paradigm 接入**(PPG / IMPALA / MuZero 等):本 change 收尾后 generic 抽象就绪,接入新 paradigm 是后续 change。
- **任何旧 ckpt 迁移 / re-train**:全部接受失效(per user 决策)。
- **obs schema / step_encoding / engine 修改**:不动。本 change 是网络层 + cfg 层重组,不动 env↔NN 协议。
- **Paradigm 算法行为改变**:纯结构 refactor + DI 化 + PPO 换 backbone,不改各 paradigm 的 loss 数学 / collector 算法 / MCTS 公式 / CFR regret update。
- **跨机训练 orchestration**:`tools.runs.sync` 只解决 metadata 同步;ssh 启动 remote train 用 bash/手动,不在本 change scope。
- **PPO closure 决议复活**(W4-PPO `2e5bc6f`):本 change 不复活 PPO closure 前的 s015-s054 ablation 历史复现路径(全部接受失效)。

## Verification gate

- **Phase 1 done**:`core/network/legacy/` git rm + `core/env_factory_legacy.py` git rm + import 全切;`pytest -n 4 training/tests/test_core_network_modules.py` 全 pass。
- **Phase 2 done**:5 paradigm 切完 + 扁平化;每 paradigm 现有 paradigm test(`test_<paradigm>_paradigm.py`)全 pass。
- **Phase 3 done**:configs 全重组;`pytest -n 4 training/tests/test_cfg_schema.py` 全 pass(新增 schema validation test)。
- **Phase 4 done**:5 个 smoke test 全 pass,wall time 每个 ≤ 2min。
- **Phase 5 done**:`tools.runs.list` + `tools.runs.show <id>` + `tools.runs.sync pull <host>` 三个 CLI smoke pass。
- **Phase 6 done**:8 个 spec delta merge 进各 capability spec.md;ADR-0009 r009 production fallback 条款标 SUPERSEDED;C6.2 r008 reproducibility 同标 SUPERSEDED;openspec validate 通过。

## Estimated workload

| Phase | LOC | 文件 |
|---|---|---|
| Phase 0 备份 + git tag + ckpt rm + configs 全删 | 0 | git tag + rm -rf |
| Phase 1 Generic primitives 重设计 | +500 / −1400 | ~10 root files |
| Phase 2 5 paradigm 切 import + 扁平化 + PPO 重写 backbone | +700 / −600 | ~17 paradigm files |
| Phase 3 cfg 层重组(`ObsShape` + ckpt schema + configs/ 重组) | +400 / −400 | ~15 files |
| Phase 4 5 smoke test | +500 / 0 | 5 新 test files |
| Phase 5 `tools/runs/` + rsync sync wrapper | +400 / 0 | ~6 new files |
| Phase 6 Spec/ADR 治理(8 spec delta merge + ADR supersede) | +300 / −300 | ~12 spec/doc files |
| **合计** | **+2800 / −2700 = +100 LOC** | ~65 files touched |
