# 设计决策 — 第三阶段：C API 与观测空间

> **MOVED to `openspec/changes/archive/0002-capi-obs-d5-d9/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0002-capi-obs-d5-d9/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0002-capi-obs-d5-d9/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


> 本文是早期 D1-D4 (DSL API 调整) 的延续,前置阅读 `../5_history/decisions_legacy/dsl_api_d1_d4.md`。

## 第三阶段：C API 与 Python RL 环境

### D5：C API 设计

**问题：** Python 需要与 Go 游戏引擎交互以进行 RL 训练。

**方案：**
- A) cgo -buildmode=c-shared：将 Go 编译为 .so/.dylib，暴露 C 函数
- B) 子进程：Go 二进制通过 stdin/stdout JSON 通信
- C) gRPC/socket

**决策：** A。训练速度最快（无序列化开销）。通过 `//export` + `-buildmode=c-shared` 导出。

**已发布的 C API 接口：** 参见 `../1_specs/engine/capi_mirror.md` §9.1 及
`gicg_engine/capi/capi.go` 中的权威来源。已发布接口全程使用
`C.int` 整数句柄（而非 `void*` 指针），`GameNew`
接受单个 JSON 配置（`*C.char`）而非单独的 seed 参数——seed 包含在配置 JSON 中。
以上最初草案已被取代；目前实际导出约 35 个函数，涵盖
生命周期（new/free/clone/snapshot/reset）、动作循环、张量观测读取
以及原始奖励事件计数器。

### D6：Python 环境

**决策：** 简单类封装 ctypes 调用。初期不继承 gym.Env——保持最小化。如需要，后续再添加 gym 包装。先用随机智能体测试。

### D7：观测空间——静态/动态分离

**问题：** Hook AST token 在每局游戏中是静态的（约 220K），而计数器值每步都会变化（约 2K）。每步传递 220K 数据会浪费计算资源。

**决策：** 分为两部分观测：

**静态（221,616 个值，每局一次）：**
- 计数器元数据：(min, max, shuffled_id) × 所有槽位（5,496 个值）
- **Char-skill refs**：`[2][ObsMaxChars=6][ObsMaxSkillsPerChar=10]` — 每 (player, char, skill_slot) 存该技能的 canonical on_skill_use hook 在 active hook 列表中的位置（或 -1 空位）。位置 (p, c) 结构编码 owner；slot 维度通过 `SkillSlotPerm[p][c]` 每 (p, c) 独立洗。这条提供对方技能的**显式**可见性，否则 agent 只能靠 legal_actions 相关性去学 skill_id → owner 映射。（120 个值）
- Hook AST token：900 个 hook × 120 个 token × 2（类型、值）（216,000 个值）
- 由 StaticEncoder 处理 → 256 维嵌入，在每局中缓存

**动态（2,157 个值，每步一次）：**
- 元信息：phase、round、is_my_turn（3 个）
- 计数器值：每槽 1 个，视角翻转（己方→敌方，1,832 个）
- 手牌：own_in_hand/deck/discard + enemy_discard + enemy_totals（322 个）

**槽位大小（理论最大值 × 1.5）：**

| 常量 | 值 | 推导依据 |
|------|----|---------:|
| ObsMaxChars | 6 | 设计文档：1-3 个角色，6 含余量 |
| ObsCharSlots | 128 | (6 固定 + 54 PerChar + 24 Self) × 1.5 |
| ObsMaxSkillsPerChar | 10 | 当前 3 技能/角色 × 3x，给天赋授予技能留余量 |
| ObsPlayerSlots | 140 | (3 计数器/卡 × 30 张卡 + 2 系统) × 1.5 |
| ObsGlobalSlots | 16 | ~5 实际 + 余量 |
| ObsMaxCardTypes | 80 | 当前 30 × 1.5 + 扩展空间 |
| ObsMaxHooks | 900 | (6 角色 × 6 技能 + 30 张卡) × 9 hook/文件 × 1.5 |
| ObsMaxTokensPerHook | 120 | 观测到的最大 80 token × 1.5 |

**槽位大小的自底向上分析：**
- 每个技能文件最多计数器数：4（刻师傅_刻印）
- 每个文件最多 hook 数：9（星愿）
- 最长 hook 体：80 个 token（天星_天星）
- PerChar 计数器类型：当前 17，按规模估算 54
- 每角色 Self/ActiveStatus：当前最多 5，按规模估算 24（6 技能 × 4）
- 每张卡 PerPlayer：最多 3（乘胜追击），按规模估算 92（30 张卡 × ~3）

**Token 词汇表：** 256 个 ID，涵盖关键字、运算符、API 调用、枚举值、ctx 字段、方法调用和字面量。计数器/技能/卡牌引用使用经过随机打乱的 ID 以实现位置不变性。

**视角翻转：** 动态观测将计数器分组为己方→敌方→全局。P1 观测时，己方=P1 的计数器，敌方=P0 的。静态观测使用规范顺序（P0=第一），因为 hook 结构是对称的。

**Anti-position-ID 洗牌汇总：**

| 对象 | 洗牌来源 | 粒度 |
|------|---------|-----|
| Counter sid | `CounterPerm` 全局 | 每个 counter ID 映射到随机 sid |
| Hook active idx | `HookPerm` 全局 | 每个 hook ID 映射到随机打乱的激活列表位置 |
| Card slot | `CardPerm`（ObsMaxCardTypes=80）| hand/deck/discard bucket 内位置 |
| Char-skill slot | `SkillSlotPerm[p][c]` 每 (p, c) 独立 | 该槽位技能在 char-skill 区内的物理 slot s |

`SkillSlotPerm` 对应的是 per-char counter 的 sid 洗牌角色：char-skill 区的 (p, c) 位置结构不洗（编码 owner），内部 slot 顺序随机 —— 防止网络学"slot 0 = 普攻"的跨局位置 ID 近路。每 (p, c) 独立生成（Fisher-Yates），所以镜像对战下同一角色在两边物理位置也不同。

### D8：get_char 统一（延后）

**问题：** `get_char(name)`、`get_active_char(player)`、`get_next_char(player, from)` 是各自独立的 API。

**计划：** 统一为基于类型分发的 `get_char`。延后至观测空间工作正常后再实施。

### D9：GameReset 策略

**决策：** 每局使用 GameNew + GameFree。计数器/hook 的随机打乱确保每局顺序不同。没有需要重置的持久状态。
