# 实现设计

## 调度

`Game.Buffs` 是全局产生顺序列表；内部 `BuffSerial` 只区分生命周期，并随快照、克隆、checkpoint 保存。
事件议程捕获实例编号，执行前检查存活。无 `order` 的系统 hook 保留固定管线行为。

回合调度先按类别与全局实例位置稳定排序，再在同类别的召唤物槽位内按先结束方重排。
这样混合阶段不会破坏普通 buff 之间的全局先后关系，也不会引入不满足传递性的排序比较器。
各 HookType 阶段保持独立；结算致死后立即终止后续议程。

DSL 的 `Tag.Summon` 在加载时转成定义的召唤物区标记。`order_on="target"` 支持挂在受击者身上的效果；
蝶印回合末从受印者构造目标，并显式指定对方为伤害 actor。
写入 hook 支持 `{order=counter, priority=...}`；实例选择采用被写 counter 的所属方，避免继承攻击者。

## 独立实例

`register_buff(b, {independent=true})` 声明零初值模板；`spawn_buff(b,value,duration[,player,char])`
创建独立层。`duration=-1` 表永久；正数表示剩余回合。绑定的衰减 hook 调用
`set_buff_duration(buff_duration()-1)`，到零删除。

实例 hook 内 `b:get/sub/set` 访问该层；外部读取得到总次数，外部仅允许 set(0) 清空模板的所有层。
新增层必须 spawn，不能含糊地写入某一层。标签写入回调收到带原实例身份的 counter 参数，
即便回调由另一项 buff 驱动，也不会改到错误的叠层。每次费用应用用 `(实例生命周期, hook)` 识别，消费 hook
也须绑定同一模板，防止同一个 hook 的多层效果一起误消费。原聚合 counter 语义保留。

## NN 与兼容性

动态尾段为 1024 × 12；每个实例只引用它实际绑定的有效 hook：
`valid, relative_owner, char, value, duration, progress, position, hook_slot, trigger, priority, death_bound, round_group`。

`round_group`：0 普通，1 召唤物且尚无先结束方，2 先结束方召唤物，3 后结束方召唤物。
模型能同时看到全局顺序、召唤物区与已知结束顺序；内部生命周期编号不进 NN。
实例状态在独立层之间分开读取；不再用整个来源文件的全部 hook 作为每层的规则上下文。
写入 hook 的 AST 和 counter 参数现在也编译成 IR。规则仍是 hook 级程序，尚未把任意复杂闭包拆成
更细的效果图；引用型装备的各程序仍通过现有条件判断区分。

BuffEncoder 增加一个数值维度；旧 v3 权重通过显式 adaptation 保留前五列并将新列置零。
严格 resume 不接受旧形状；旧回放缺失真实顺序或旧观测布局时应重新采样。
线端容量仍为 1024 行，独立叠层或扩池超过容量会明确报错，不截断。

## 限制

当前池与依赖的回合状态、消费与写入效果已迁移；未宣称所有非当前配置角色都已迁移。
固定系统事件不是临时 buff，仍在各自管线位置。临时双方排序规则待用户后续核对。
只证明接口、生命周期与已列交互，不证明策略可泛化；零样本、少样本、旧环境遗忘仍需正式对照实验。
