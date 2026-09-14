# Contracts

- CardTarget SHALL resolve the selected player/character from the active card
  execution frame, also through nested/deferred effects and cloned execution.
  Missing selection SHALL fail rather than default to player 0, character 0.
- Targeted weapon eligibility SHALL inspect the selected character. Candidate
  enumeration SHALL defer the weapon check until a concrete target exists.
- Declared card energy costs SHALL gate legality and be consumed exactly once,
  before card effects. An invoked skill already marked Paid SHALL not pay again.
- Canonical skill energy changes SHALL use the energy-event pipeline. A gain
  SHALL dispatch its after-event only for a positive actual counter increase;
  reaching the cap SHALL not fabricate further energy transfers.
- Tag write callbacks SHALL receive a concrete reference to the counter being
  changed, preserving its reference kind. Summary proxies are not valid values
  for a callback that reads or writes the affected counter.
- Healing contexts SHALL preserve the initiating skill/card identity.
- `cancel()` SHALL mark the active hook context cancelled. Nested hooks SHALL
  restore the enclosing context on return or failure; reset and clone SHALL
  not retain an active hook context. Calling cancel without a hook SHALL fail.
- 蝶鳞追加状态伤害不得再次触发自身技能伤害钩子；赤蝶回火的低血量条件用
  `hp * 2 < max_hp` 精确计算。蝶鳞在基础治疗前增加 1 点，避免重复判断时
  被基础治疗改变条件。

## 用户确认核心规则与工作约定（2026-09-11）

- 乘胜追击：每回合第四次需要消耗骰子的操作，总骰费最多减少 3。
  优先扣指定元素费用，再扣同色费用，最后扣无色费用；不减少能量费用。
  计入付费非战斗牌、技能和主动切换。其他费用修正先结算，已经免费的
  操作不计数；第四次因本卡变免费仍推进计数，第五次正常付费。
  激活本卡的操作不计数；查询合法动作不推进计数，回合开始重置。
- 新增通用 `cost_reduce(ctx, amount)`，不硬编码卡名。与 cost_mod 一样
  记录 AppliedMods，并使用独立稳定 token 312 进入规则 IR。
- 以逸待劳：过量治疗也算，反击使用治疗事件请求量，不按实际回血差值。

证据等级补充：用户直接确认第四次付费操作减 3、受限优先、过量治疗
计入；激活不计数、其他减费先结算以及受限槽内部顺序是实现工作约定，
未单独获得确认。参见 [基线 Q01](../freeze-current-rule-baseline/rules.md)。
