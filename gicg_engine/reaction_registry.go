package engine

// ADR-0019 §B.3 — Reaction declare registry。
//
// 支持 DSL 新增反应(始基 / 烈绽放 / 超绽放 / 未来反应):任何 DSL 文件
// declare_reaction("名") 即可,engine 0 hardcode 反应名;reaction.lua 在
// 反应触发分支调 set_reaction_kind(R_X) 写 EventContext.ReactionKind。
// obs encoder 编码到 typed slot。
//
// Idempotent: 重复 declare 同名 return 同 ID。ID = 0 reserved for
// Reaction.None(no reaction triggered),DSL declared 反应从 ID=1 起。

// ReactionNone — sentinel ID for "no reaction triggered"。
// EventContext.ReactionKind 默认 0 = ReactionNone;DSL set_reaction_kind 写 > 0。
const ReactionNone = 0

// DeclareReaction — DSL declare_reaction("X") 调用,首次见 alloc 新 ID,
// 重复见 return 已 alloc ID。返 ID > 0(0 reserved)。
func (g *Game) DeclareReaction(name string) int {
	if g.ReactionRegistry == nil {
		g.ReactionRegistry = map[string]int{}
		g.ReactionNames = []string{""} // index 0 sentinel "ReactionNone"
	}
	if id, ok := g.ReactionRegistry[name]; ok {
		return id
	}
	id := len(g.ReactionNames) // 1, 2, 3, ...
	g.ReactionRegistry[name] = id
	g.ReactionNames = append(g.ReactionNames, name)
	return id
}

// ReactionName — ID → name 反查(obs labels / debug)。
// Returns "" for unknown ID (含 ReactionNone=0)。
func (g *Game) ReactionName(id int) string {
	if id <= 0 || id >= len(g.ReactionNames) {
		return ""
	}
	return g.ReactionNames[id]
}

// ReactionCount — 已注册反应总数(不含 ReactionNone sentinel)。
// obs encoder 用此定 typed enum 上界(N=32 起步,对齐 §B.3 ADR)。
func (g *Game) ReactionCount() int {
	if len(g.ReactionNames) == 0 {
		return 0
	}
	return len(g.ReactionNames) - 1
}
