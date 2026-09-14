# 显式规则引用图

新增 `Game.BuildObservationRuleGraph`、C API `GameGetRuleGraphJSON` 和 Python
`env.get_rule_graph()`。此接口与原始平坦观察分开，不移动原有字段。

版本1包含：
- counter_owners：每个counter观察槽的canonical玩家/角色，padding或全局为-1。
- counter_links：counter观察槽、active hook索引、hook内绑定序号、已有method token。
- card_links：当前shuffle卡牌槽、该卡牌规则文件的active hook索引。

引用从既有声明/closure审计元数据生成，图不包含动态值、手牌组成、牌堆顺序、名称字符串。
write回调的触发counter另以binding=-1/method=0标记；未分配lazy目标不编造观察槽。
它是静态访问关系，不是逐指令解释器，不声称替代DSL执行语义。

重要发现：当前IR使用文件级生成的TypedBinding ID，不是动态counter SID；不能把两者直接gather。
引用图避免依赖这项不存在的数值对应。当前卡池实际导出664条counter链接、4条card链接。
124个active counter槽中有87个出现在图内；未链接机械槽主要为equipped引用槽及始基标记。
未链接数量仍需保留，不能通过删除这些输入获得虚假的不变性；装备引用另有typed entity描述。

当前阶段：接口已实现，Go跨20种布局引用保持、schema不随动态值变化测试通过；
Python真实环境索引与只读检查1项通过；CAPI编译与factory测试通过。
网络尚未接入此图，D1/shuffle目标仍未完成。
