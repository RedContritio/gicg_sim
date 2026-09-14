# 历史交接记录（非当前状态）

原 docs/HANDOFF.md 的时间线存档；其中“正在运行”等措辞只描述当时。当前状态见 [实时入口](../0_status/README.md)。

**决策**:Go 引擎**只**知道 characters / hand / deck / round / turn;**不**知道 HP、能量、元素、护盾、冻结、行动点、反应。所有游戏机制 = counter + hook,在 DSL 表达。

**为什么**[指令]:04-10 13:16 作者原话——「**引擎对这些术语都应该保持无知。引擎只应该知道角色、手牌、牌堆、回合、行动轮这些概念就够了**。」论证方式是举反例:04-10 17:30「召唤物、支援这些规则**不应该编码到 go 里**。注意,卡牌【星愿】会更改这种机制。你应该把**尽可能多的机制都放在外部 lua 处理**。」——即任何机制都可能被某张卡改写,写死在引擎里就锁死了扩展性。

**否决过**:
- 04-10 17:05 否决把 AP 消耗放进 Go:「这些信息**不应该由 go 引擎维护**」。
- 04-10 13:14 否决把冻结做成引擎机制:「冻结是检查状态发现无法打出技能」。
- 05-05 05:02 否决 Reaction 特化:「**系统 dsl 不等于系统应该知道**」。
- 04-25 05:48 否决为实验改引擎:「骰子暴露,这种应该用配置,而不是反复改引擎」。

**反向边界**(引擎该管的):枚举常量、技能/卡牌名字、依赖图计算都在 Go(04-11 22:54 / 22:59、04-10 20:01)。作者的划法是:**引擎负责把系统事实写进 counter,不负责解释它**(04-10 11:42)。

**已知偏离**:2026-05-28 的审计发现 9 处引擎无知泄漏(Element/Dice 枚举、伤害管线 6 子阶段、护盾 builtin、死亡复活等),累计 ~1450 LOC。2026-05-29 作者裁定 **won't-fix**(backlog I32):「W3 标记先不做。这个成本太高了。」理由是「当前 RL 训练效果的根因不是 engine 设计偏离,先解决科研瓶颈再回头治架构」。

### 3.2 数据-引擎分离 + 为什么是 Go

**决策**:游戏规则在 Lua DSL(`data/`),引擎是 Go 通用执行器,Python 只做训练不做规则。想加机制 → 改 DSL,不改 Go。

**为什么**[指令]:04-10 09:04 一句话同时定了两件事——「**1 的结果我不满意。游戏数据和引擎应当分离,另外我们引擎层用 go,只在 dl 的时候静态链接到 python**。」这是 Go + c-shared 的原始理由,和「数据/引擎分离」是同一个决策。

**否决过**:自研 DSL 格式(04-10 09:02 提问,09:08 定「lua 吧」)。

### 3.3 Counter + Hook 模型

**决策**:扁平 `[]Counter` 数组(Value/Init/Min/Max + 自动 clamp)+ 扁平 hook 数组(按 HookType 分发,Priority 高先,同优先级按注册顺序)。**Go 内无 filter matching**——DSL callback 自己 early-return。

**为什么**[指令]:04-10 08:34 作者本人提出,动机直接来自 RL——「hook 对 counter 的读写全部使用引用的形式,我们在训练的时候**可以任意打乱 counter 和 hook 的位置,来强迫学习**。」即 counter/hook 的扁平化是为了 **shuffle 抗位置记忆**。

**推论:一切都必须是 counter,无例外**。04-11 05:46:「**静态属性、派生属性这里,也应该用 counter 来处理**……否则 hook 读数据的行为在 counter 和静态属性上区别太大了。」

**否决过**:
- 04-10 13:06 否决 counter 的 `reset` 属性:「有点太硬编码了。我们不如**接受 hook 数量翻倍的代价,每个 counter 自己带一个负责清理的 hook**」——理由是生命周期要可见可读。
- 04-10 18:30 否决 Go 侧 filter:「我**不想要 filter 在 go 中处理**」。
- 04-10 17:43 否决聚合反应 hook:「**火+冻结,火+冰,火+水。这三个应该是三个完全独立的 hook**」。

**Counter scope**:04-10 08:53 提出,08:57 定为 counter 级属性,含 `PerChar` 等(创建时看似单个,读取时传目标)。

### 3.4 Observation 不用 ID —— 项目第一条规矩

**决策**:agent observation 必须用 functional property,**绝不**用 ID;DSL 只看 `*SkillRef` / `*CardRef`(typed),不暴露 int `.id`;shuffle 防位置记忆。

**为什么**[指令]:开工第三条指令,04-10 08:21——「**不赞同。id 会鼓励 agent 学习到 id 和效果的绑定关系吧?我希望这两者解耦。**」紧接着 08:29 提出正解:「我们能不能将 **DSL 直接作为输入**,让网络自己学习到 DSL 的效果。」

这条规矩被反复执行了两个月:04-12 11:33「我们为什么要存储 id 而不是存储 skill ref?」;04-15 11:51「**能否不提供 id 概念,而是让 dsl 拿到的就是 ref?**」;回放格式同样禁 ID(04-12 02:46)。

**最终形态**[代码]:2026-05-19 的 IR 改造——把 DSL 的 AST 编译成三地址码 IR 送进 obs。动机是 05-19 10:54 的反例:「我希望理解代码,哪怕是有限的理解,**否则我做个 shuffle,有条件伤害+2 和无条件伤害+2,看起来不就一样了**」。作者同时要求解耦(05-19 11:13「留出将来改成其他 ir 形式的接口」)。

### 3.5 Declare / Get 模式 —— 用隐式依赖解决加载顺序

**决策**:`create_counter` / `declare_skill` / `declare_card` 用 named declare-or-get,positional args。declare 携带 init/min/max 且多次 declare 必须完全一致否则 panic;get 不含这三个字段。

**为什么**[指令]:04-10 19:44 作者原话——「所有 declare 的调用**必须初始值,min max 这些完全相同,如果不同就 panic 出来**……这样,我们遇到 get 的时候就可以先不继续处理,直到 declare 声明了再回来处理。也就是说,**我们创建一种隐式依赖关系,来解决加载顺序的问题**。」

**否决过**:助手用 retry 解决加载顺序(04-10 19:59「我注意到你用了 retry,但我们实际上可以生成依赖图来加载」)→ 改为 04-10 20:01「**依赖图应该 go 里面计算**」。

**配套约束**:每个 lua 文件完全隔离、自包含,只通过 hook / counter / ref 交互(04-10 17:57、18:12)。由此派生出 **char-skill 文件不能 `get_card("X")`** 的架构约束(静态 topo 扫描下会成环),反向引用走 `sharedFiles` 声明。

### 3.6 DSL 表达力是被**刻意**限制的

**决策**:不支持 closure return / 顶层 function / 顶层全局表赋值 / for 循环 / pairs。Sentinel 用 `-1`。

**为什么**[指令]:04-10 19:05——「**去掉这两个的目的是将 dsl token 集合尽量减少,同时几乎完全声明式。**」核心是让 DSL 的 token 集合小到网络能学会。

**「原语膨胀」是最高频的否决理由**(至少 8 次):04-10 08:51「原语集合会越来越膨胀」;04-10 17:36「**match_pair 又是什么?你引入的新函数吗?这类太复杂了**」;04-11 03:54「**所有使用次数少于 5 次的,我们都需要逐个评审必要性**」;04-14 22:17 / 04-15 10:10 每次改动都追问「**这次新增了哪些 DSL 原语?**」。

**API 收敛的典型**:04-10 21:26「**不应该是 get category,就应该用 get counter 这一个 api!**」,改为单入口 + options 参数。

**守卫机制**:04-11 03:17 提出用 AST 统计监控非法 lua——现在是 `gicg_engine/dsl/audit_test.go`(builtin 白名单)。04-11 03:39 明确否决了用 Python 脚本做这件事:「**不要这个方案。我们用 go 的测试来做这个工作。**」

### 3.7 自研解释器,不是 LuaJIT

**决策**:`gicg_engine/interp/` 是从零写的 Lua 子集解释器,编译成 Go 闭包。**没有 LuaJIT,没有 cgo 桥**。

**演变**[指令]:最初计划用 LuaJIT(04-10 09:31「lua 可能需要用 luajit 来保证性能」),04-11 23:17 被作者本人推翻:「我们现在的 counter + hook 机制既然已经足够完善了,**我们完全可以将这个 dsl 自己实现一个小子集来做吧,这样应该能避开跨语言调用的成本?**」

**真正的动机不只是性能**:04-12 00:01——「我关注的是**纯引擎模拟**这里。这样我们**后续做回放之类的都会好很多,而且数据直接被 go 持有了,方便管理**。」

**这条现在是硬立约**:2026-05-28 讨论 Lua 解释器性能优化时,作者裁定「H5 列为长期优化项,短时间不考虑」,并记明**换 LuaJIT 违反 `openspec/project.md` 立约**;若真要优化,路径是 bytecode cache / 热 hook 移到 Go native,**不切外部 VM**。

**代价**:Lua 后端和对拍被彻底删除(04-12 02:03「既然我们现在已经没有了 lua 版本,我们不需要维护 lua 的了。我们放弃对拍」)。

### 3.8 回放格式 = 对局定义格式

**决策**:一种格式同时是回放导出格式和局面导入格式,人类可读,不含 ID,不用随机数种子。

**为什么**[指令]:04-12 02:44——「这种格式需要能**完整复刻一整局**……**这个格式既是我们的回放导出格式,也可以导入到任意一个时间点**,来进行残局对局或者对拍。」04-12 12:58 补充:「我们**不需要存储 end state,而是保存每回合开始的状态**」。

**否决过**:04-12 02:50 否决了助手的初版格式,作者手写了想要的样子(静态状态块 + 逐动作流水 + 回合末静态状态);04-13 15:45「**replay 不应该是 json**」;伤害类型等变量名要求用中文(04-12 03:00)。

**集成方式**:04-12 02:17「**回放应该是一个开关,所有测试默认打开**。而不是你专门去写一份新的测试代码。」

### 3.9 训练层:core / paradigm 拆分

**决策**[代码]:`training/core/` 算法无关(protocols / actor / network / buffer / inference / eval / matchup),`training/paradigms/<name>/` 是 5 个适配器。**5 个 paradigm 互不 import,均只 import core**。

**为什么**[指令]:04-23 09:57——「我希望重构范围更大一下。例如**异步训练循环应该是通用的部分,而不是放在 az 里**。按照这个思路,把特定算法和通用框架分开」。2026-05-15 13:15 收口:「不用这么保守,我希望**这些所有算法方案都统一管线**」,并允许破坏兼容(05-17 00:28「重设计,允许破坏已有兼容,以方案简洁优美为准」)。

**「不许算法专属」是反复出现的否决**:05-15 12:26「这几个 tools **不应该叫 dmc** 吧?这些不限制训练方案」;05-20 12:18「不要 dmc perf,这应该是通用的 perf trace」;05-22 17:54「这部分为什么是 dmc config,不应该是通用的吗」。

**5 paradigm 现状**(`openspec/project.md` §5 + [记忆]):

| Paradigm | 状态 | 数据点 |
|---|---|---|
| PPO | **Closed** 2026-04-26 | Stage 3 F1-D2 = 0.344,物理不可达 0.40 |
| AZ 纯自博弈 | **Closed** 2026-04-28 | mirror Nash 锁死,plateau 0.06-0.15 |
| AZ + BC warm-start | **Closed** | r010-012 = 0.167,把 BC 的 0.75 摧毁 -0.58 |
| Deep CFR | **Closed** | r008 iter 199 比 iter 20 还差 |
| BC alone | 生产 fallback | r009 ≈ 0.75 vs F1-D2,但**不是 RL 答案** |
| DMC | 停工前的活跃线 | run 150 峰值 vs random 77.5% / vs F1-D2 **5.1%** |

**判死刑的标准**[指令]:必须 multi-seed(04-25「相同训练流程,seed 影响这么大吗?」→ 单 seed 不作强度判据);基线不是 random 而是 **F1-D2**(dice_greedy depth-2,04-24 03:39 作者怀疑「random 是否本身足够强」后引入的分级贪心基线);每轮训练完必跑 gauntlet。

### 3.10 引擎 lib 不得感知 RL —— I29 的边界

**决策**[指令]:05-21 18:39 作者原话——「等等,我希望 **gicg 本身 lib 是不感知 rl 的,只提供环境**。现在方案能做到吗」。

**落地**[代码]:Go 侧 actor 全部代码进新顶层 `gicg_actor/`,`gicg_engine/` 零侵入。

**I29 的全过程是本项目最痛苦的一段**,值得记下来因为它定义了「什么算验证通过」:
- 动机:N=16 Python actor 占 11.4 GB RSS,InfServer decode 瓶颈在 14× pickle.loads 串行。
- 作者拒绝把它做成可配置项:05-22 11:08「为什么现在的 actor backend 是可配置项。**不应该全量用 go 吗?不要道歉然后乱改,说明理由。**」
- 第一版 Go 实现**比 Python 还慢**。作者的质问是转折点:05-24 23:50「**go 方式的到底比 python 慢在哪?理论上最差也应该一致吧。是你的实现方式问题吗**」→ 直接导致完全重设计。
- 根因[记忆 `feedback_python_arch_mimicry_for_go_port`]:跨语言 port **必须严格 mimic 原进程模型和 IPC**,只替换内部计算;偏离架构(把 N+2 进程塌缩成 2 个、加 bridge 层)**by construction 不可能超过 baseline**。
- 最终方案 R7:N 个独立 Go subprocess,each 1 actor goroutine,镜像 Python mp 的 N+2 拓扑。Mac 上 5-seed fair bench **1.54x**,N=2/4/8 全部 1.21-1.73x,验收通过(2026-05-26)。

### 3.11 运行时行为只由 cfg 决定,禁止环境变量

**决策**[指令]:05-23 22:41「停一下,**也不应该用环境变量,而是换成配置**」→ 22:46 上升为规约:「顺带规约成,**全部运行时行为都应该只由 cfg 决定**。」连 dev/diagnostic flag(PERF_TRACE / GICG_MEM_PROBE)也走 `cfg.debug`。例外只有 build-time / Python I/O setup / OS BLAS 线程数。

[代码] commit `1b1c87c` 「剩余 5 user-facing runtime env var 全砍」+ `a675e62`。

**同源决策:远程配置必须内联在训练 cfg 里**。05-20 连续三次否决独立配置源:
- 「**不要单独设计一个 remote 目录**,就直接通用目录 根据 cfg 决定去哪里监控,去哪里训练,去哪里同步」
- 「**不要指向 host.toml 之类的**。remote 的配置应该就放在训练配置里,**一份训练配置就应该是固定的一组配置**」
- 「为什么需要这么单个配置文件支持多个 host。只需要单个配置文件,只有两种,一个是 local,一个是 remote」

[代码] 现在每个训练 cfg 自闭包 `[meta].host` + `[remote]` 4 字段,工具按 cfg dispatch。

### 3.12 禁止手写 ssh / 临时脚本 —— 工具必须真能用

**决策**:所有远程操作走 `tools/runs/*`,**绝不手写 `ssh` / `scp` / `tar | ssh`**。

**为什么**[指令]:这条是被作者骂出来的。05-21 19:15「**?为什么要写一个临时 ps1?不能用工具吗**」;05-23 15:16「状态检查也应该用工具,而不是手写 ssh」;05-27 20:50「**?我们不应该有现成工具吗,不要每次都造轮子**」;06-03 01:17「为什么要 ssh?不能直接用存量脚本吗」。

最重的一句在 05-20 20:33:「**就应该全部解决。我们这个工具从创建到现在都多久了,就因为每次方案设计不充分,你刚才还想跑完单测就提交,才导致一直没法实际可用。**」

**由此产生两条通用规约**[记忆]:
- **工具类 spec 必须含 production e2e smoke** — 止步于 unit test mock 是 anti-pattern。实例:`kill.py` 通过了 reviewer 审查,真跑才发现 100% 不可用。
- **单命令 atomic 优于多步 lifecycle** — `tools/runs/` 五轮 review 约 40 个 bug 中 70%+ 是「协调点 bug」,改成单命令 + 内部状态机消除整类。

### 3.13 严格契约、fail-loud、不留兼容

三条互相咬合的纪律,贯穿全程,是理解这个代码库风格的钥匙。

**a) 不做防御式编程,错误必须可见**:04-10 13:09「**既然已经在内部管理了,就不需要考虑防御性编程了**」;04-10 17:46「防御在 go 端检查就行,**如果发现索引不对应该直接 panic**」;04-15 13:32「**静默忽略?这是什么?我们所有不在预期中的都应该直接报错。**」;04-29 11:08「**缺则 raise**……**不要有兜底,全部直接 raise**」。

**b) 不接受 workaround / fallback / mock**:04-28 20:05「**不要模拟和任何 workaround,直接实现**」;04-30 05:59「**不允许任何 work around 和 fallback**」;04-30 16:36「**我不接受 mock 和 placeholder。必须先填**」;04-30 11:49「**我不认同这次的很多改法。我认为只是绕开了问题。我希望从架构底层来解决问题**」。

**c) 不保留向后兼容**:04-15 21:39「不考虑向后兼容」;05-07 14:40「不刻意保留兼容或者 fallback。如果新的方式支持需要不兼容,可以改写原来的」;05-08 12:44「**ckpt 不保留兼容**。其他全部都改」。废弃子系统一律**物理删除**,不留并行栈或迁移垫片(实例:`core/network/legacy/` 删除;AZ legacy 栈净删 ~3300 LOC)。

**d) 禁止静默决策**[记忆 `feedback_silent_decisions`]:选 cfg、加 override、删测试、给「不现实」的估算,全都要先给理由 + 数据 + 列选项 + 等拍板。「加 cfg 字段当 escape hatch = silent backwards-compat anti-pattern」。

### 3.14 性能声明必须 fair benchmark 验证

[记忆 `feedback_performance_must_verify` / `feedback_bench_fairness_audit_first` / `feedback_bench_variance_5seed_required`]:

- 「X 比 baseline Y 快」类工作,**必须同 commit / 同 cfg / 同硬件跑 fair benchmark**,达标才算 ship gate。memory 里的历史数字不算 fair baseline。
- 跨语言/架构 ratio > 2x 时,**必须先审计两侧是不是同一个 workload**,再去怀疑 runtime/GC/scheduler。惨痛实例:I29 的 0.28x 几乎全部来自 Python 侧 `mp_factories.py:75` 静默没注册 f1d2/f1d4 + `_dmc_spec_sampler:103` 硬编码 random,即 Python 在偷跑便宜的对手。修完 Go 反超 3.66x。
- Mac M4 上 3-seed 的 CV 高达 110%,**默认 5 seed**,CV > 60% 加 seed,不许引用 3-seed 数据做验收。

---

## 4. 停在哪里

### 4.1 时间线(2026-06-01 ~ 06-12)

| 日期 | 发生了什么 |
|---|---|
| 06-01 ~ 06-03 | I31(AZ/CFR mp-pool 统一)+ 维护治理收尾,squash 合并 main。最后一个 commit `c87c73c` 落在 06-03 20:38。 |
| 06-03 | 捞 run 150 的对局回放做归因。结论:**赢 F1-D2 靠开局神抽**;势均力敌时输在「**过早结束回合**」。作者否决了「直接复用 F1 特征」的捷径(担心诱导 overkill),追问「dmc 完全解决不掉吗?」。当晚设计 PER,走 OpenSpec 流程。 |
| 06-04 | PER 实现 + 启动 run 151。13:52 问「是否存在什么结构性问题导致学习效果差」。15:40 决定「**做一下 γ < 1 的改动**」,杀掉旧训练重跑 run 152。21:59 观测到结果「**这些似乎都显著弱于原始的峰值?有什么原因吗**」——**这个问题没有答案**。 |
| 06-05 00:03 | 「**停掉吧,我要用 windows 设备了。**」训练是因为设备被挪用而停,不是跑完。留下两个待办:总结训练教训、探索复用 ckpt 续训。00:06「等明天了新 session 做」——**再没做**。 |
| 06-06 ~ 06-10 | **无任何记录**,断档 6 天。 |
| 06-11 | 复工,只有 4 条指令,全是方向评审。22:42 拍板「学会」的定义(见下)。23:30「**1 必须 2 允许搜索**」。 |
| 06-12 | 修 06-11 审计发现的引擎 bug + 改 DSL 卡牌。11:47 抛出未闭环的问题:「**还有其他需要处理的 bug 吗?我印象中现在的测试完全看感觉写的,是否有什么方案能优化**」。13:02 撞额度限制。**14:58「继续」——最后一条指令。** |

**项目不是收尾停的,是断在半句话上。**

### 4.2 `i33-roundend-actor-ctx` 的三个 commit 是什么

[代码] 这批改动是 **06-11 combo 审计三大发现的修复**,一一对应:

**a) 回合末 actor 视角 bug(引擎,最严重)**
`gicg_engine/game_counter.go` 新增 `firePerPlayerHook()`:每次 per-player hook 调用前 `PushEvent` 一个 actor 帧,hook 结束前 `DrainDeferred` 再弹帧。

修的是什么:回合结束 hook 阶段事件栈为空,`currentEvent()` 静默返回零值帧(Player=0),导致所有回合末 `deal_damage`/`heal` 的目标解析恒以 P0 为 actor → **P1 方的「以牙还牙」在 run 150 的全部 1024 局回放中 100% 友伤自己**。

**b) fail-loud 契约(引擎)**
新文件 `gicg_engine/event_must.go` 提供 `Game.MustCurrentEvent(site)`:事件栈空时 **panic** 而不是静默返回零值帧。消费端断言点铺到 `DealDamage` / `Heal` / `GainEnergy` / `ConsumeEnergy` / `resolveTargetHP` / `invoke_skill`。同步写进 `openspec/specs/engine-dsl/hook.md` §7 作为 SHALL 契约。

**c) F4 显式牌组(引擎 + Python + cfg 全链)**
修的是 `deck.go` 的 `eligible[:15]` 静默截断(每局牌组恒定 15 张,悄悄丢卡)。新增 `GameConfig.players[i].deck` → `GicgEnv(decks=...)` → 训练 cfg `[scenario].deck_0/deck_1` 全链路,并规定:未声明显式牌组且 eligible 超过 `target_size` 时 **fail game creation 并列出溢出卡名**。11 个 config 文件同步加了显式 deck。

**d) 「以逸待劳」卡改写(DSL)**
[指令] 06-12 11:26 原话:「**B1,但是改成 +2 当前出战角色属性的骰子,用来制衡强度。**」
[代码] 该卡原本依赖一个**不存在的 `ap` counter**(被 topo loader 静默排除),现改为 `add_dice(p, element_to_dice_color(c.element), 2)`,并把两处 `defer_fn` 改成直接嵌套 `deal_damage`。**代码与指令完全吻合。**

**e) 8 个新测试文件,共 1567 行**
`round_end_actor_test.go`(257)/ `card_yiyidailao_test.go`(318)/ `deck_explicit_test.go`(196)/ `empty_stack_actor_test.go`(155)/ `pool_load_guard_test.go`(137)/ `loader_topo_test.go`(142)/ `test_deck_explicit.py`(203)/ `test_scenario_decks.py`(159)。

**f) 3 个临时验证脚本**(repo 根目录,`_f4_probe_decks.py` / `_f4_verify_cfg_decks.py` / `_f4_verify_fixture_decks.py`,**故意未提交**)。做法是:迁移前用 `before` 模式抓取截断期各场景的牌组多重集 + 两个种子下的有序发牌序列存到 `/tmp/f4_probe_before.json`,迁移后用 `after` 模式以显式牌组重跑并逐位比对,**证明 F4 是 bit-level 行为等价的**。docstring 写明「delete after acceptance」。由于 `/tmp` 基线已失效,**这个等价性验证现在无法复现,只能信任当时的结论**。

### 4.3 下一步原本要做什么

按证据强度排序:

1. **[强,06-11 23:30 拍板]** 引入 **ExIt(搜索 + 迭代蒸馏)训练配方**。作者对「真正学会」的定义是:「需要有能力找到那种,**连续多次选择看似不利的做法,但构成巧妙 combo 获胜路线**的 agent 才算是真正学会,**就像 AlphaZero 一样**」;并明确 ①combo 必须是获胜必经路(necessity 读法)②验收时允许 agent 带搜索。
2. **[强,06-12 记忆]** **场景升级到 v_legacy 2v2**。理由:1v1 operative 场景 combo 有物理上限(唯一 combo 家族「蝶火附魔 → 附魔枪 → 以牙还牙 → 蒸发」在 F1-D2 视野下严格劣,256 局仅用 4 次;d≥3 产不出)。v_phase2 被**否决为捷径**(7 角色全是 deferred 骨架)。最便宜的证伪点是先跑 **2v2 F1-D2 selfplay 200 局 dump + L2 标注**。
3. **[强,06-12 记忆 closure 重划]** AZ 栈**就是现成的 ExIt 循环**,唯一结构缺口是 `paradigms/az/paradigm.py:108` 的 `del opp_pool`(spec A5.2 锁 mirror),换成 DMC 已验证的 OpponentPool 约 **550-700 LOC**。同时 `value_target_source=mcts_value` **从未启用**,是 pilot 必备对照臂。
4. **[中,06-12 11:47 未闭环]** 测试质量治理。作者原话:「我印象中现在的测试完全看感觉写的,是否有什么方案能优化」。**没有答案落盘。**
5. **[中,06-05 承诺但未执行]** 总结训练教训 + **复用已有 ckpt 续训**。

---

## 5. 已知的坑与未决问题

### 5.1 6 个已确认但未修的引擎状态机 bug —— 最高优先级

[代码] 2026-08-10 实测确认。`.claude/worktrees/wf_76b120e8-90f-4/gicg_engine/tests/audit_clone_gaps_test.go` 是 06-12 的审计探针(文件头注明「**NOT intended for merge as-is** — 测试 FAIL 即确认对应 bug 存在」)。我把它跑了一遍,**6 个测试全部 FAIL**:

| # | 症状 | 影响面 |
|---|---|---|
| 1 | `DeepCopy` 丢失 `Game.Preparing` | MCTS 搜索克隆状态时丢准备技能 |
| 2 | `RestoreFrom` 丢失 `Game.Preparing` | 同上,restore 路径 |
| 3 | `RestoreFrom` 残留幻影 support | 搜索回溯后支援区状态错误 |
| 4 | `ResetDynamicState` 跨 episode 泄漏 `Preparing` 和 support | **训练每局重置时状态串台** |
| 5 | `SpecialtyCardRef` 在 clone 间共享(克隆的装备漏回原 runtime)+ 跨 episode 泄漏 | **训练 + 搜索双重污染** |
| 6 | `on_after_damage` 内 `g.Defer` 排队的 fn 被静默丢弃 | DSL 行为静默失效 |

定义位置:`gicg_engine/game_clone.go`(`DeepCopy` L15 / `RestoreFrom` L138 / `ResetDynamicState` L198)。

**关键:未提交的 i33 工作区没有碰这三个函数,所以这 6 个 bug 在当前工作区里依然存在。** #4 和 #5 是跨 episode 泄漏,直接影响所有训练数据的正确性。#6 已被 DSL 侧绕过(「以逸待劳」的注释明写「不用 defer_fn — 动作帧 PopEvent 不 drain,挂帧 defer 会被静默丢弃」),但**引擎层没修**。

另外两个 worktree 的探针:`wf_76b120e8-90f-31/probe_defer_afterdamage_test.go`(与 #6 同源)、`wf_76b120e8-90f-32/pending_overwrite_repro_test.go`(候选 bug「PendingAction 无条件覆盖」)。**后者我跑了,PASS —— 该候选 bug 未复现,可以判为证伪。**

### 5.2 全部历史 eval 数字已被污染

[记忆 `project_combo_audit_findings_2026_06_11`] 回合末 actor bug 意味着 **run 150 的 5.1% 等所有跨该 bug 的数字修复后作废,需重测**。caseA/caseB 实际上是两个不同规则的环境。修复语义(以 hook owner = `ctx.ActorPlayer` 为 actor)会影响 4+ 张卡的行为 + 全部 e2e replay 漂移。

同一条记忆里还建议 **γ=0.99 resume 取消/推迟到 bug 修复后**。

### 5.3 γ=0.99 resume:cfg 已就绪,在 `i32-dmc-per` 分支上,从未执行

[记忆 06-04] 写明下一步是 `configs/dmc/stage3_gamma99_resume.toml`,标注「cfg ready,待执行」。

[代码] 该文件**不在 `main` 上**,在未合并分支 `i32-dmc-per` 的 commit `35befd3`(2026-06-05 00:07)里 —— 那正是训练被停掉(06-05 00:03「停掉吧,我要用 windows 设备了」)后几分钟做的收尾提交。commit message 末尾就写着「下一 session 执行」+ 完整命令。

参数:γ=0.99(γ^30≈0.74,远优于 run 152 的 γ=0.97 的 0.40)/ lr 5e-5→2.5e-5 减半保护 feature / resume 后 buffer 自然清空。执行命令:

```bash
git checkout i32-dmc-per   # 或先把 6 个 commit 合进来
.venv/bin/python -m tools.runs.train --resume \
  artifacts/202606021719_000150_dmc_stage3_b_v_legacy/ckpts/ckpt_65000.pt \
  configs/dmc/stage3_gamma99_resume.toml
```

**但先别跑**:同一份记忆在 06-11 审计后追加了「**γ=0.99 resume 已建议 cancel/推迟到 bug 修复后**」—— 因为回合末友伤 bug 污染了 run 150 的全部基线数字(§5.2)。现在 bug 已在 `i33` 修掉,**该 resume 若要执行,应先合并 i33 并重测 run 150 基线**。

### 5.4 训练结论本身悬空

