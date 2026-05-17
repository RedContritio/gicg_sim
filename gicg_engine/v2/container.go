// Package enginev2 — DSL v4 prototype namespace。
// 不破坏 v1 engine,独立 build + test 验证关键 axiom (A1/A2/A5/A25)。
package enginev2

// A1 — State 统一容器: 标量 (counter) + 集合 (slice of Item) + substate state container。
// 本 prototype 实现 scalar + collection 两类;substate 单独文件。
//
// 全 typed schema (no map[string]any, no any-typed Item): RL obs encoder 可做 fixed-slot
// encoding;hook 作者编译期可见所有字段。Item 是 typed interface,concrete: Card/Summon/SkillRef。

type ContainerKind int

const (
	KindScalar ContainerKind = iota
	KindCollection
	KindSubstate
)

// Owner 标识容器归属 (player, char)。char=-1 表示 PerPlayer。
// player=-1 表示 system 容器。
type Owner struct {
	Player int
	Char   int
}

func SystemOwner() Owner { return Owner{Player: -1, Char: -1} }

// HiddenFrom 标识哪些 player 看不见容器内容。空 = 全公开。
type HiddenFrom []int

// Scalar 容器 — 整数值 + bound (A1)。
// Destroyed: A16 owner-detach lifecycle — 容器被显式销毁后,引用它的 hook 自动 detach (tombstone)。
type Scalar struct {
	Name       string
	Value      int
	Min, Max   int
	Tag        int
	Owner      Owner
	HiddenFrom HiddenFrom
	Destroyed  bool
}

// Get/Set/Add/Sub: 直接读写 (用于 substate state 私有 mutation,A20);
// 走 propose-commit 的 mutation 由 transaction 层 apply。
func (s *Scalar) Get() int { return s.Value }
func (s *Scalar) clamp() {
	if s.Value < s.Min {
		s.Value = s.Min
	}
	if s.Value > s.Max {
		s.Value = s.Max
	}
}

// Collection 容器 — 有序 typed Item 列表 (A1 + A27 instance/shared)。
// Destroyed: A16 owner-detach (同 Scalar.Destroyed)。
type Collection struct {
	Name          string
	Items         []Item
	MaxSize       int
	Owner         Owner
	HiddenFrom    HiddenFrom
	ItemOwnership string // "instance" | "shared"
	Destroyed     bool
}

func (c *Collection) Len() int      { return len(c.Items) }
func (c *Collection) At(i int) Item { return c.Items[i] }
func (c *Collection) Iter() []Item  { return c.Items }
func (c *Collection) Insert(i int, item Item) {
	c.Items = append(c.Items[:i], append([]Item{item}, c.Items[i:]...)...)
}
func (c *Collection) Append(item Item) { c.Items = append(c.Items, item) }
func (c *Collection) RemoveAt(i int) Item {
	if i < 0 || i >= len(c.Items) {
		return nil
	}
	item := c.Items[i]
	c.Items = append(c.Items[:i], c.Items[i+1:]...)
	return item
}

// 全局 typed enums 在 enums.go;Item interface + concrete 在 items.go。

// ===== L3 obs:LastTransitions (typed transition log) =====
//
// 每 SubAction commit 后 engine append TransitionEntry 到 Game.LastTransitions。
// bounded 16 (与 MaxProvenance 一致),超 → drop oldest。
// RL obs encoder 把 LastTransitions encode 成 fixed-shape tensor (16 × 7 typed fields)。
// 让 RL 可从 obs 唯一推理 last K 步因果,而不只学行为后效。

type TransitionEntry struct {
	SubAction     SubActionKind
	Actor         Owner       // (player, char) — 谁触发
	Target        Owner       // (player, char) — 受影响方
	Element       ElementType // 伤害/反应类的元素;无关时 ElementNone
	TriggerSource TriggerSource
	Value         int  // damage/heal/draw count/etc.
	Cancelled     bool // commit phase rollback (A2)
}

const MaxLastTransitions = 16

// GamePhase 在 enums.go。

// Game 是 prototype 的 state 容器集合。生产版本会有更多字段 + 三层 pipeline state。
type Game struct {
	Scalars         map[string]*Scalar
	Collections     map[string]*Collection
	NextStepID      int                // 用于 RNG seed deterministic + replay
	Pending         []*PendingDecision // A25 PDR 队列
	LastTransitions []TransitionEntry  // L3 obs ring (bounded 16)

	// game-level meta (RL obs 必读)
	Round  int
	Turn   int       // 当前行动方 (0/1)
	Phase  GamePhase // 当前阶段
	Winner int       // -1=进行中, 0=p0 胜, 1=p1 胜, 2=平局
}

func NewGame() *Game {
	return &Game{
		Scalars:     map[string]*Scalar{},
		Collections: map[string]*Collection{},
		Winner:      -1, // 进行中
	}
}

func (g *Game) DeclareScalar(name string, init, min, max int, owner Owner) *Scalar {
	s := &Scalar{Name: name, Value: init, Min: min, Max: max, Owner: owner}
	s.clamp()
	g.Scalars[name] = s
	return s
}

func (g *Game) DeclareCollection(name string, maxSize int, owner Owner, ownership string) *Collection {
	c := &Collection{Name: name, MaxSize: maxSize, Owner: owner, ItemOwnership: ownership}
	g.Collections[name] = c
	return c
}

// AppendTransition — engine.FireSubAction 完成后调,把 typed transition entry 写入 ring。
func (g *Game) AppendTransition(t TransitionEntry) {
	g.LastTransitions = append(g.LastTransitions, t)
	if len(g.LastTransitions) > MaxLastTransitions {
		g.LastTransitions = g.LastTransitions[1:]
	}
}

// Clone 深拷贝 — 验证 A11 forward-simulatable atomic step。
// Plain-data 容器 + typed Item (非 closure),直接复制。
func (g *Game) Clone() *Game {
	ng := NewGame()
	ng.NextStepID = g.NextStepID
	ng.Round = g.Round
	ng.Turn = g.Turn
	ng.Phase = g.Phase
	ng.Winner = g.Winner
	for k, s := range g.Scalars {
		ns := *s
		nhf := make(HiddenFrom, len(s.HiddenFrom))
		copy(nhf, s.HiddenFrom)
		ns.HiddenFrom = nhf
		ng.Scalars[k] = &ns
	}
	for k, c := range g.Collections {
		nc := *c
		ni := make([]Item, len(c.Items))
		copy(ni, c.Items)
		nc.Items = ni
		nhf := make(HiddenFrom, len(c.HiddenFrom))
		copy(nhf, c.HiddenFrom)
		nc.HiddenFrom = nhf
		ng.Collections[k] = &nc
	}
	// LastTransitions 深拷 (typed slice of value type, copy 即深)
	if len(g.LastTransitions) > 0 {
		ng.LastTransitions = make([]TransitionEntry, len(g.LastTransitions))
		copy(ng.LastTransitions, g.LastTransitions)
	}
	// Pending 不深拷,prototype 阶段假设 pending 在 step 边界为空
	return ng
}
