package engine

import "math/rand"

// GameConfig 描述对局配置。
// 引擎只关心结构信息（角色数量、技能数量、牌堆）。
// HP、能量、冻结等 counter 由 DSL declare_char/declare_skill 创建。
type GameConfig struct {
	Players [2]PlayerConfig
	Seed    int64
}

type PlayerConfig struct {
	Chars []CharConfig
	Deck  []CardInst
}

type CharConfig struct{}

func NewGame(config GameConfig) *Game {
	g := &Game{
		Hooks:    NewHookRegistry(),
		Winner:   -1,
		FirstEnd: -1,
		Phase:    PhaseNotStarted,
	}

	for pi := 0; pi < 2; pi++ {
		pc := config.Players[pi]
		ps := &g.Players[pi]

		for ci := range pc.Chars {
			ch := CharInfo{
				PlayerIdx: pi,
				CharIdx:   ci,
				Alive:     true,
			}
			ps.Chars = append(ps.Chars, ch)
		}

		ps.ActiveChar = -1 // 未选择出战角色
		ps.Deck = append([]CardInst{}, pc.Deck...)
		ps.InitDeck = append([]CardInst{}, pc.Deck...)
	}

	rng := rand.New(rand.NewSource(config.Seed))
	g.InitShuffle(rng)

	return g
}

// StartGame 进入选人阶段（双方选择出战角色）
func (g *Game) StartGame() {
	g.Phase = PhaseSelectActive
	g.Turn = 0 // P0 先选
}

// Reset 重置游戏到初始状态
func (g *Game) Reset(seed int64) {
	for i := range g.Counters {
		g.Counters[i].Value = g.Counters[i].Init
	}
	for pi := range g.Players {
		for ci := range g.Players[pi].Chars {
			g.Players[pi].Chars[ci].Alive = true
		}
		g.Players[pi].ActiveChar = -1
		g.Players[pi].DeclaredEnd = false
		g.Players[pi].Hand = nil
		g.Players[pi].Deck = append([]CardInst{}, g.Players[pi].InitDeck...)
	}
	g.Phase = PhaseNotStarted
	g.Round = 0
	g.Turn = 0
	g.FirstEnd = -1
	g.Winner = -1
	g.PendingAction = nil
	g.eventStack = g.eventStack[:0]
	g.depth = 0

	rng := rand.New(rand.NewSource(seed))
	g.InitShuffle(rng)
}
