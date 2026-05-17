# C API + observation space (D5-D9)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0002-capi_obs_d5_d9.md` at P1-T1)
**Original date:** 早期(D1-D4 后续)
**Original status:** Accepted (Stage A; D8 延后,D5/D6/D7/D9 落地)
**Supersedes:** —
**Superseded by:** —

## Why

Stage A 阶段需要把 Python RL 训练 stack 接到 Go game engine。同时需要确定 observation 空间形态以
喂网络。本 ADR 是 D5-D9 五个决策的合记。

## What

- **D5 C API 设计** — A (cgo `-buildmode=c-shared` 暴露 C 函数);训练速度最快(无序列化开销)。
  已发布约 35 个 `//export` 函数,覆盖生命周期 / action loop / tensor obs / 原始 reward 计数器;接口
  全程用 `C.int` 整数句柄(非 `void*`),`GameNew` 接受单一 JSON cfg(seed 含其中)。Authoritative
  source: `gicg_engine/capi/capi.go` 与 `docs/1_specs/engine/capi_mirror.md` §9.1。
- **D6 Python env** — 简单 ctypes wrapper class,**不**继承 `gym.Env`(保持最小化);初期用随机
  agent 验证。需要 gym 兼容时后续加 wrapper。
- **D7 obs 静态/动态分离** — 每局静态 (221,616 values, encoded once → 256-d) + 每步动态 (2,157
  values)。Hook AST token 约 220K 静态;counter values 约 2K 动态。每步传 220K 浪费算力,故拆。
  - 静态: counter meta + char-skill refs + hook AST token (`StaticEncoder` → 256-d)
  - 动态: phase/round + 视角翻转 counter values + 手牌信息
  - 槽位上限按"理论最大值 × 1.5"取(`ObsMaxChars=6` / `ObsCharSlots=128` / `ObsMaxSkillsPerChar=10`
    / `ObsPlayerSlots=140` / `ObsGlobalSlots=16` / `ObsMaxCardTypes=80` / `ObsMaxHooks=900` /
    `ObsMaxTokensPerHook=120`)
- **D8 `get_char` 统一** — 延后(`get_char(name)` / `get_active_char(player)` / `get_next_char` 暂分立)
- **D9 GameReset** — 每局 `GameNew + GameFree`;counter / hook 的 anti-position-ID 洗牌确保每局顺序
  不同;无需 reset 的持久 state

## Affected specs

- `engine-capi` (待建,P1-T2/T6 抽 capi 接口 SHALL 时 backfill)
- `engine-obs` (待建,obs 槽位上限 + 静态/动态分离 SHALL)
