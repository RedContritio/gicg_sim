# Design (retrospective)

## Consequences

### D5 (C API)
- `-buildmode=c-shared` libgicg.dylib 与 Python ctypes 形成稳定 ABI(整数 handle,JSON cfg)
- 约 35 个 `//export` 函数;`gicg_engine/capi/capi.go` 是 source of truth,`docs/1_specs/engine/capi_mirror.md` 是文档镜像
- Python 不感知 Go object 内部,只持 `C.int` game handle

### D6 (Python env)
- `gicg_env/engine.py` 是 ctypes wrapper;`gicg_env/env.py::GicgEnv` 是 RL env class
- gym 兼容需要时通过 thin wrapper 暴露;不被 RL framework lock-in

### D7 (obs 静态/动态分离)
- StaticEncoder 在 episode 起点 encode 一次,cached 整局
- 动态 obs 每步重算
- **Anti-position-ID 洗牌矩阵**:
  | 对象 | 洗牌来源 | 粒度 |
  |---|---|---|
  | Counter sid | `CounterPerm` 全局 | 每个 counter ID → 随机 sid |
  | Hook active idx | `HookPerm` 全局 | 每个 hook ID → 随机激活列表位置 |
  | Card slot | `CardPerm` (ObsMaxCardTypes=80) | hand/deck/discard bucket 内位置 |
  | Char-skill slot | `SkillSlotPerm[p][c]` 每 (p, c) 独立 | char-skill 区内物理 slot |
- 视角翻转:动态 obs 把 counter 分组成 己方 → 敌方 → 全局;静态 obs 用 canonical (P0 first) 因 hook 结构对称
- char-skill refs `[2][6][10]` 区显式提供敌方技能可见性,否则 agent 只能靠 legal_actions 相关性
  学 skill_id → owner 映射

### D8 (get_char 延后)
- 现 API 分立(`get_char(name)` / `get_active_char(player)` / `get_next_char(player, from)`)
- 后续考虑 type-dispatched 统一;不阻塞 obs 工作

### D9 (GameReset)
- 简化:每局 fresh game,无 reset 状态污染
- 洗牌天然保证 episode-to-episode 顺序差异(no_ids 原则)

## Tradeoffs revisited

- C API 选 cgo 不选 gRPC/socket:序列化开销 0,但 Python 与 Go 必须同进程
- obs 槽位 ×1.5 余量:浪费 RAM 换扩展性 / 避免每加新机制改 shape
- Hook AST tokens 静态 cached:训练时 episode 起点 256-d encode 一次,后续 step 零开销;比每步 push
  220K 数据省 ~85% 通信

## References

- `docs/2_decisions/adr-0002-capi_obs_d5_d9.md` (mirror, P1+ phase 删)
- `gicg_engine/capi/capi.go` — C API source of truth
- `docs/1_specs/engine/capi_mirror.md` §9.1 — 接口文档
- `docs/5_history/decisions_legacy/dsl_api_d1_d4.md` — 前置 D1-D4
- `gicg_engine/observation.go` — 视角翻转实现
- memory `feedback_no_ids` — anti-position-ID 原则
