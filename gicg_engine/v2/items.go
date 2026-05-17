package enginev2

// Item interface + concrete typed Item types。
// Collection.Items 是 []Item, encoder / extractKey 用 type assertion typed dispatch。
// 加新 Item type 时:实现 ItemKind() + 加 ItemKind enum 值 + extractKey case 等。

// Item — Collection.Items 元素的 typed interface。
type Item interface {
	ItemKind() ItemKind
}

// MarkerRef — declared marker (取代 ctx-internal marker name 字符串)。
// declare_marker(owner) → ref;hook propose marker / cross-hook 查 marker 都用 ref。
type MarkerRef struct {
	Name  string // 仅 trace/debug, 不是 user 输入
	Owner Owner  // 谁 declare 的
}

// CardRef — hand/deck/discard collection 元素 (A27 instance ownership)。
type CardRef struct {
	Ref          int      // 全局 unique 卡 id (declare_card 时 engine 分配)
	DrawnAtRound int      // v1 reward shaping 复用
	CostTotal    int      // sort key + cost preview;实际 cost 走 CostSpec
	Kind         CardKind // RL obs encoding 区分牌型
}

func (c *CardRef) ItemKind() ItemKind { return ItemKindCard }

// SummonRef — summon zone collection 元素。
type SummonRef struct {
	Ref     int         // declared summon template id
	Owner   Owner       // 谁召出来的(player, char)
	Hp      int         // 召唤物血量(部分召唤物有,如兔兔伯爵)
	Usage   int         // 剩余使用次数(典型 2-3,0 = 消失)
	Element ElementType // 召唤物元素
}

func (s *SummonRef) ItemKind() ItemKind { return ItemKindSummon }

// SkillRef — declared skill (attached to char),用于 char 的 skill_set collection (A17)。
// Cost *CostSpec 由 cost_payment.go 定义。
type SkillRef struct {
	Ref     int
	Owner   Owner       // 哪个 char 的 skill
	Element ElementType // 普攻/技能元素
	Cost    *CostSpec   // 释放代价(A24)
}

func (s *SkillRef) ItemKind() ItemKind { return ItemKindSkillRef }
