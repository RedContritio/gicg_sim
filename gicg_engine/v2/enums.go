package enginev2

// 全局 typed enum 集合 — 取代旧字符串字段。
// 加新 enum 值要修改 enum + 业务 hook 编译期 affected, 这正是 typed schema 的目标。

// ElementType — 7 元素 + 物理 (A22 hook filter / SkillRef.Element / SummonRef.Element)。
type ElementType int

const (
	ElementNone ElementType = iota // 物理伤害
	ElementFire
	ElementIce
	ElementWater
	ElementElectro
	ElementGeo
	ElementAnemo
	ElementDendro
)

// CardKind — 卡分类 (RL obs 区分牌型 + 业务 hook filter)。
type CardKind int

const (
	CardKindAction    CardKind = iota // 行动牌(占用骰子但非装备/事件/支援)
	CardKindEquipment                 // 装备牌(武器/圣遗物/天赋)
	CardKindEvent                     // 事件牌(一次性)
	CardKindSupport                   // 支援牌(场上持续)
	CardKindFood                      // 食物牌(子类,RL 区分有意义)
)

// ItemKind — Collection items 的 typed dispatch tag。
type ItemKind int

const (
	ItemKindCard ItemKind = iota
	ItemKindSummon
	ItemKindSkillRef
)

// SubActionKind — A5 三层 pipeline 的 SubAction 枚举。
type SubActionKind int

const (
	SubActionGeneric      SubActionKind = iota // 测试 fallback / placeholder 不允许 — 仅 e2e 反应链测试用
	SubActionDealDamage                        // 扣血(走伤害管线)
	SubActionHeal                              // 回血
	SubActionDraw                              // 摸牌
	SubActionDiscard                           // 弃牌
	SubActionDiceOp                            // 骰子操作(掷/换/消耗)
	SubActionAuraChange                        // 元素附着变化
	SubActionSummonCreate                      // 召唤物创建
	SubActionFormChange                        // 形态切换(A29)
	SubActionPickSubstate                      // 进入 PDR 挑选 substate
	SubActionCostPayment                       // A24 dice 支付
	SubActionReaction                          // 元素反应触发
)

// TriggerSource — A22 取代 silent_kind 白名单。
// engine 在调 SubAction 入口时塞,业务 hook 自己 filter (e.g. `if not is_player_action then return end`)。
type TriggerSource int

const (
	TriggerPlayerAction      TriggerSource = iota // RL agent 主动选 action
	TriggerEquipOnPlay                            // 装备打出立即触发(战玉璋 / 烈絮)
	TriggerSpecialty                              // 特技
	TriggerReactionSubdamage                      // 反应副伤害(扩散 / 穿透)
	TriggerSummonAutoAction                       // 召唤物自动出招
	TriggerCardSubAction                          // 卡内嵌套(白垩 → 派蒙)
	TriggerEngineInternal                         // engine round_end auto draw
)

// GamePhase — 游戏阶段 (typed, 取代 v1 string)。
type GamePhase int

const (
	PhaseInit     GamePhase = iota // 起始 / 投掷
	PhaseRollDice                  // 投掷骰子
	PhaseAction                    // 行动阶段
	PhaseEndPhase                  // 结束阶段
	PhaseGameOver                  // 终局
)
