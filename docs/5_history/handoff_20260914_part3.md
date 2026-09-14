# 历史交接记录（非当前状态）

原 docs/HANDOFF.md 的时间线存档；其中“正在运行”等措辞只描述当时。当前状态见 [实时入口](../0_status/README.md)。

[指令 06-04 21:59] PER(run 151)和 γ=0.97(run 152)两个改动**都比原始 run 150 的峰值差**,作者问「有什么原因吗」,**归因没做完训练就被停了**。

代码位置:PER(`training/paradigms/dmc/sum_tree.py` + `buffer.py` 优先级采样)和 γ<1 都在未合并的 `i32-dmc-per` 分支上,**`main` 上没有**(§2.1)。
[记忆] 已有的教训:PER 不适合 MC return(per-transition TD error ≠ per-action credit);γ<1 方向正确但 0.97 太激进(γ^30≈0.40,压缩 Q 动态范围 60%);ε 和 γ 不该同时改(run 152 混淆了两者效果)。

### 5.5 环境依赖

- **Windows GPU box**(`ssh dev@192.168.31.56`,`D:\gicg_dev`,9950X3D + 5070 Ti,torch 2.12+cu130)是唯一的 GPU 训练机。[指令 06-05] 已被挪作他用。所有 GPU 训练路径依赖它可用。详见 [记忆 `reference_windows_gpu_box`]。
- **sm_120 必须用 cu130 build**,不是随便装个 torch 就行。
- 配 remote cfg 前**必须先 ssh 实测 hostname 真实值**(历史上配错过 `DEV-PC` vs 实际 `DESKTOP-GHJCC7Q`)。
- [记忆 `project_pre_existing_sandbox_failures_2026_05_17`] Claude Code sandbox 会 deny `bind()` / `nice()` syscall,导致 21 个测试失败;**非沙盒环境全 PASS,不需要改代码**。别被这些误导。

### 5.6 其他已归档的坑

- **r009 BC ckpt 已不可 load** — ADR-0019 的 obs schema 加了 252 个 typed slot,旧 ckpt 全失效(BREAKING by design)。生产 fallback 实际是空的。
- **I29 未完成的尾巴**(backlog):D1(Win box fair bench 从未跑)/ D2(production no-cap fair bench)/ D3(AZ/PPO/CFR/BC 的 Go subprocess port,各 500-800 LOC)/ D4(N>2 的 e2e 测试覆盖)/ D5(Linux GPU box 复验)。
- **I32 引擎无知重构:won't-fix**,9 项泄漏保留作 audit reference。重新评估的前置条件写在 backlog I32 里。
- **正式卡池录入未开始** — 300+ 张真实卡 × 几十行 Lua。infra 就绪,源数据在 `~/Documents/gicg_sim/data/raw/`(JSON),需要写 JSON → Lua DSL 转换器。
- **`docs/**/*.md` 有 500 行 / 50KB 的 pre-commit 硬限制**,改文档时注意。

### 5.7 一个文档陈述与代码不一致的地方

`docs/0_status/README.md` 的 `last_updated` 是 **2026-06-02**,`openspec/project.md` 是 **2026-05-15**。两者都**早于**项目实际停工的 06-12,因此**都不反映 6 月的 DMC 实验结论、combo 审计发现和 06-11/06-12 的方向重定**。§4 是这段时间唯一的叙述。

`openspec/project.md` §5 的 paradigm 表也未包含 6 月的 closure 重划(见 §5.8)。

### 5.8 closure 集合在停工当天被改写了 —— 别照着旧表走

[记忆 `project_rl_routes_closure_2026_05_12`,该文件 **2026-06-12 04:54 被更新**,是最后一次记忆写入] 作者在 06-12 做了三条 rescope:

1. **原来的 blanket 禁令「不要 propose 任何 self-play MCTS 变种」被改写**:mirror self-play(双侧同网自博弈,任何 stage/hparam)**维持 closed**;但 **ExIt vs 固定对手族(agent 单侧 MCTS + F1-D2/random 固定对手 + historical ring)开放** —— 这个配方从未被测试过,不在 ADR-0009 的数据级禁列内,**是新主线**。
2. **r010「AZ+BC warm-start」的封条限定为 mirror 配方下**(死因是 mirror 对手分布漂移 + 探索噪声冲洗 sharp policy);固定对手 ExIt 下的 BC 冷启动(prior + value head init)**开放**。
3. **s069 以 operative pilot 形态重开**(2v2 场景 n_rollouts 两档对照);不做玩具场景 bit-exact 复现。

**NFSP / Deep CFR 维持 closed**(06-11 审计以方差分析判死:~30 决策 horizon 下 ES 组合爆炸 + OS 权重恒截断)。

**这条如果不看,很容易照着 `openspec/project.md` 的旧表把唯一开放的方向也当成 closed。**

---

## 6. 重新上手路径

假设三个月后回来,按这个顺序:

**第 0 步(先做,5 分钟):搞清楚代码在哪个分支上。**
```bash
cd ~/Projects/gicg_mono
git log --oneline -1 main                      # c87c73c，停在 2026-06-03
git log main..i33-roundend-actor-ctx --oneline # 3 个引擎修复，未合并
git log main..i32-dmc-per --oneline            # 6 个 PER/γ 提交，未合并
```
**`main` 上没有 6 月的任何工作。** 直接从 main 开工会踩回已经修掉的回合末友伤 bug,也会看不到 PER / γ<1 的实现。建议先决定这两个分支怎么合(作者惯例是 squash),再动手。

**第 1 步:读状态,10 分钟。**
1. 本文件 §4(停在哪里)—— 唯一覆盖 6 月的叙述。
2. `~/.claude/projects/-Users-redcontritio-Projects-gicg-mono/memory/MEMORY.md` 的**前 6 条**(倒序按时间,最上面就是最新的 06-11/06-12)。
3. `.../memory/project_true_learning_definition_combo_2026_06_11.md` —— 目标语义拍板。
4. `.../memory/project_combo_audit_findings_2026_06_11.md` —— 三大发现。
5. `.../memory/project_rl_routes_closure_2026_05_12.md` —— **只看末尾的 2026-06-12 rescope 一节**(§5.8)。

**第 2 步:读立约,20 分钟。**
6. `CLAUDE.md`(仓库根)—— 构建/测试/远程训练/pre-commit 的操作手册。
7. `openspec/project.md` §4 Key Invariants —— I1-I9 九条硬立约。
8. 本文件 §3 —— 每条立约的**来源和被否决的替代方案**(project.md 只写结论不写理由)。

**第 3 步:验证环境还活着,15 分钟。**
```bash
go build ./... && go test ./gicg_engine/...
go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/
.venv/bin/python -m pytest -n 4 gicg_env/tests/ -q
.venv/bin/python -m pytest -m smoke training/tests/ -q
```

**第 4 步:按目的分叉。**

- **想继续科研主线** → 读 §4.3 的 1-3 条 + `training/paradigms/az/paradigm.py:108`(mirror 锁的位置)。第一个动作应该是 §4.3 第 2 条的 **2v2 先导 dump**(最便宜的证伪点,作者估合成概率只有 0.10-0.15)。
- **想先把工程债还掉** → 读 §5.1 的 6 个 bug,从 `gicg_engine/game_clone.go` 开始。这 6 条里 #4 #5 影响训练数据正确性,应该先于任何新训练。
- **想理解引擎/DSL** → `openspec/specs/engine-dsl/spec.md` + 5 个 subtopic;范本卡是 `data/pools/v_legacy/cards/*/以牙还牙.lua`(作者 04-11 02:30 亲自指定为 DSL 范本)。
- **想跑训练** → `CLAUDE.md` 的 "Remote training" 一节。**先确认 Windows box 还在**。

**第 5 步:开工前的规矩。**
- 新 RL 任务前**必读 closure 集合**(§5.8),明确说出新方向属于哪条未做候选、与 closed 集合的区别在哪。
- 任何性能声明必须同 commit / 同硬件跑 fair bench,≥5 seed(§3.14)。
- 提交前必须与负责人确认(全局 `~/.claude/CLAUDE.md` 规定,无例外)。

---

## 附:本文档未能确认的事项

助手回复已被自动清理,以下问题**无法从现有材料还原**,如实标注:

1. **06-12 那批改动当时为什么没提交** —— 是撞了额度限制(13:02 `/rate-limit-options`)后没来得及,还是刻意留着等验收?两种都说得通,无证据区分。(改动本身已于 2026-08-10 补提交,见 §2.1。)
2. **两个 feature 分支为什么都没合并回 main** —— `i32-dmc-per`(6 commits)和 `i33-roundend-actor-ctx`(3 commits)都停在未合并状态。作者的惯例是「阶段性成果再合并回去」+ squash 合并(06-02 03:09),所以**很可能只是没走到那一步**,而非刻意隔离。但无直接证据。
3. **06-12 「3 4 都按建议处理」里的 3、4 具体指什么** —— 助手给的 follow_up 列表已清理。从改动倒推,大概率是 fail-loud 契约和 F4 显式牌组,但**这是推断,不是确认**。
4. **06-12 要求的 "mps/cpu 测试" 有没有跑过** —— 04:52 作者要求「做完修复之后记得先在当前设备跑 mps/cpu 测试」,**无任何执行记录**。我在 2026-08-10 补跑了 Go 全量 + `gicg_env/tests/` + `training/tests/`,全部通过(§2.2),但这是 CPU 路径;**MPS 后端路径仍未验证**。
5. **run 151 / 152 的最终诊断** —— 06-04 21:59 的提问没有留下答案。
