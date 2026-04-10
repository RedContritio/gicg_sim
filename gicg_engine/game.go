package engine

import "math/rand"

// CharInfo 引擎只知道角色的结构信息，不知道 HP/能量/冻结等游戏概念。
type CharInfo struct {
	PlayerIdx int
	CharIdx   int
	Skills    []int
	Alive     bool
}

// CardInst 引擎只知道卡牌的身份标识。
type CardInst struct {
	Ref int
}

type PendingCard struct {
	PlayerIdx    int
	CardRef      int
	BattleAction bool
	TargetMode   int // 1=own_char, 2=enemy_char
}

type PlayerState struct {
	Chars       []CharInfo
	ActiveChar  int
	Hand        []CardInst
	Deck        []CardInst
	InitDeck    []CardInst // Reset() 时恢复
	DeclaredEnd bool
}

// --- 事件栈（每层是队列） ---

type EventFrame struct {
	ActionCtx ActionContext
	Source    Source
	Player    int
	Char      int
}

type deferredEntry struct {
	Frame     EventFrame
	Fn        func(g *Game) // 自动执行
	Action    *Action       // 需要玩家输入（Fn 为 nil 时使用）
	NeedInput bool
}

type eventLayer struct {
	Current  EventFrame
	Deferred []deferredEntry
}

const MaxDepth = 16

type Game struct {
	// 核心数据
	Counters []Counter
	Hooks    *HookRegistry
	Players  [2]PlayerState

	// 游戏状态
	Phase    Phase
	Round    int
	Turn     int // 当前行动方（0 或 1）
	FirstEnd int // 本回合先声明结束的玩家（-1 = 尚无）
	Winner   int // -1=进行中, 0=P0胜, 1=P1胜, 2=平局

	PendingAction     *Action
	PendingCardTarget *PendingCard

	// 事件栈
	eventStack []eventLayer
	depth      int // 递归保护

	// Shuffle 排列
	CounterPerm []int
	HookPerm    []int

	// Counter → 角色映射（由 DSL 层注册）
	counterCharMap map[int][2]int // counterID → [playerIdx, charIdx]
}

func (g *Game) AddSkill(playerIdx, charIdx, skillID int) {
	ch := &g.Players[playerIdx].Chars[charIdx]
	ch.Skills = append(ch.Skills, skillID)
}


func (g *Game) RegisterCounterChar(counterID, playerIdx, charIdx int) {
	if g.counterCharMap == nil {
		g.counterCharMap = make(map[int][2]int)
	}
	g.counterCharMap[counterID] = [2]int{playerIdx, charIdx}
}

// --- Counter ---

func (g *Game) CreateCounter(value, min, max int) int {
	id := len(g.Counters)
	c := Counter{
		Value: value,
		Init:  value,
		Min:   min,
		Max:   max,
	}
	c.Clamp()
	c.Init = c.Value
	g.Counters = append(g.Counters, c)
	return id
}

func (g *Game) ReadCounter(id int) int {
	return g.Counters[id].Value
}

func (g *Game) ReadCounterMin(id int) int {
	return g.Counters[id].Min
}

func (g *Game) ReadCounterMax(id int) int {
	return g.Counters[id].Max
}

// --- 写入管道 ---

func (g *Game) FireBeforeWrite(id int, op Op, ctx *EventContext) bool {
	for _, h := range g.Hooks.GetBeforeWrite(id, op) {
		if !h.Enabled {
			continue
		}
		h.Fn(g, ctx)
		if ctx.Cancelled {
			return false
		}
	}
	return true
}

func (g *Game) ApplyWrite(id int, op Op, value int) {
	c := &g.Counters[id]
	switch op {
	case OpSet:
		c.Value = value
	case OpAdd:
		c.Value += value
	case OpSub:
		c.Value -= value
	}
	c.Clamp()
}

func (g *Game) FireAfterWrite(id int, op Op, ctx *EventContext) {
	for _, h := range g.Hooks.GetAfterWrite(id, op) {
		if !h.Enabled {
			continue
		}
		h.Fn(g, ctx)
	}
}

func (g *Game) WriteCounter(id int, op Op, value int) {
	g.depth++
	defer func() { g.depth-- }()
	if g.depth > MaxDepth {
		return
	}
	ctx := &EventContext{
		CounterID: id,
		Op:        op,
		Value:     value,
	}
	if cur := g.currentEvent(); cur.ActionCtx != ActNone {
		ctx.ActionCtx = cur.ActionCtx
		ctx.Source = cur.Source
		ctx.ActorPlayer = cur.Player
		ctx.ActorChar = cur.Char
	}
	if !g.FireBeforeWrite(id, op, ctx) {
		return
	}
	g.ApplyWrite(id, op, ctx.Value)
	g.FireAfterWrite(id, op, ctx)
}

// --- 事件栈 ---

func (g *Game) PushEvent(frame EventFrame) {
	g.eventStack = append(g.eventStack, eventLayer{Current: frame})
}

func (g *Game) PopEvent() {
	if len(g.eventStack) > 0 {
		g.eventStack = g.eventStack[:len(g.eventStack)-1]
	}
}

func (g *Game) CurrentEvent() EventFrame {
	return g.currentEvent()
}

func (g *Game) currentEvent() EventFrame {
	if len(g.eventStack) == 0 {
		return EventFrame{}
	}
	return g.eventStack[len(g.eventStack)-1].Current
}

// Defer 将效果追加到当前事件帧的延后队列
func (g *Game) Defer(fn func(g *Game)) {
	if len(g.eventStack) == 0 {
		fn(g) // 无事件帧时立即执行
		return
	}
	layer := &g.eventStack[len(g.eventStack)-1]
	layer.Deferred = append(layer.Deferred, deferredEntry{Fn: fn})
}

// DeferAction 将需要玩家输入的延后动作追加到队列
func (g *Game) DeferAction(action *Action) {
	if len(g.eventStack) == 0 {
		g.PendingAction = action
		return
	}
	layer := &g.eventStack[len(g.eventStack)-1]
	layer.Deferred = append(layer.Deferred, deferredEntry{
		Action:    action,
		NeedInput: true,
	})
}

// DrainDeferred 执行当前帧的延后队列
func (g *Game) DrainDeferred() {
	if len(g.eventStack) == 0 {
		return
	}
	layer := &g.eventStack[len(g.eventStack)-1]
	for len(layer.Deferred) > 0 {
		entry := layer.Deferred[0]
		layer.Deferred = layer.Deferred[1:]
		if entry.NeedInput {
			g.PendingAction = entry.Action
			return // 暂停，等待玩家输入
		}
		if entry.Fn != nil {
			entry.Fn(g)
		}
	}
}

// --- 事件触发辅助 ---

func (g *Game) FireEventHooks(hookType HookType, ctx *EventContext) {
	for _, h := range g.Hooks.GetEventHooks(hookType) {
		if !h.Enabled {
			continue
		}
		h.Fn(g, ctx)
		if g.Phase == PhaseGameOver {
			return
		}
	}
}

// FirePerPlayerHooks 触发 PerPlayer 事件 hook。
// system hook (OwnerPlayer == FilterAny) 对每个玩家各 fire 一次（ctx.ActorPlayer 依次设为 0, 1）。
// character hook (OwnerPlayer >= 0) 只 fire 一次（ctx.ActorPlayer 设为 OwnerPlayer）。
// playerOrder 控制玩家遍历顺序（如先手/后手）。
func (g *Game) FirePerPlayerHooks(hookType HookType, ctx *EventContext, playerOrder []int) {
	for _, h := range g.Hooks.GetEventHooks(hookType) {
		if !h.Enabled {
			continue
		}
		if h.OwnerPlayer == FilterAny {
			// system hook: fire once per player
			for _, pi := range playerOrder {
				ctx.ActorPlayer = pi
				h.Fn(g, ctx)
				if g.Phase == PhaseGameOver {
					return
				}
			}
		} else {
			ctx.ActorPlayer = h.OwnerPlayer
			h.Fn(g, ctx)
			if g.Phase == PhaseGameOver {
				return
			}
		}
	}
}

// --- Shuffle ---

func (g *Game) InitShuffle(rng *rand.Rand) {
	n := len(g.Counters)
	g.CounterPerm = rng.Perm(n)

	totalHooks := g.Hooks.nextID
	g.HookPerm = rng.Perm(totalHooks)
}

func (g *Game) GetState() []float32 {
	out := make([]float32, 0, len(g.Counters)*3)
	perm := g.CounterPerm
	if len(perm) != len(g.Counters) {
		perm = make([]int, len(g.Counters))
		for i := range perm {
			perm[i] = i
		}
	}
	for _, idx := range perm {
		c := g.Counters[idx]
		out = append(out, float32(c.Value), float32(c.Min), float32(c.Max))
	}
	return out
}

// --- 公开辅助 ---

// SetAlive 供 DSL (death.lua) 调用
func (g *Game) SetAlive(playerIdx, charIdx int, alive bool) {
	g.Players[playerIdx].Chars[charIdx].Alive = alive
	if !alive {
		g.checkWin()
	}
}

// DrawCard 为玩家抽一张牌
func (g *Game) DrawCard(playerIdx int) {
	p := &g.Players[playerIdx]
	if len(p.Deck) == 0 {
		return
	}
	if len(p.Hand) >= 10 {
		p.Deck = p.Deck[1:]
		return
	}
	p.Hand = append(p.Hand, p.Deck[0])
	p.Deck = p.Deck[1:]
}

// SetWinner 供 DSL (timeout.lua) 调用
func (g *Game) SetWinner(winner int) {
	g.Winner = winner
	g.Phase = PhaseGameOver
}

// checkWin 检查是否有一方全灭
func (g *Game) checkWin() {
	p0Dead := g.checkAllDead(0)
	p1Dead := g.checkAllDead(1)
	if p0Dead && p1Dead {
		g.Winner = 2
		g.Phase = PhaseGameOver
	} else if p0Dead {
		g.Winner = 1
		g.Phase = PhaseGameOver
	} else if p1Dead {
		g.Winner = 0
		g.Phase = PhaseGameOver
	}
}

func (g *Game) checkAllDead(playerIdx int) bool {
	for _, ch := range g.Players[playerIdx].Chars {
		if ch.Alive {
			return false
		}
	}
	return true
}
