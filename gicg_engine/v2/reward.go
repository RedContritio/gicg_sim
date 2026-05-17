package enginev2

// A13 — Reward attribution at commit。
// Per-proposal owner (player + char + buff_source),RewardAccum 在 commit 阶段后累加。
// **buff_source 仅 analytics + 卡作者 debug,不进 RL reward** (memory `feedback_no_ids`)。
// RL reward 仍按 player-level (DamageDealt / DamageReceived / HealDone / ShieldAbsorbed / etc.)。

type RewardAccum struct {
	DamageDealt    int
	DamageReceived int
	HealDone       int
	HealReceived   int
	ShieldAbsorbed int
}

type RewardAccumPair [2]RewardAccum // index = player

func NewRewardAccum() *RewardAccum {
	return &RewardAccum{}
}

// AccumulateAfterCommit — engine 在 commit phase 成功后调用,根据 ctx.Proposals 累加 reward。
// 关键: rollback 不调此函数 → reward 与 state delta 一致 (R6 缓解 attribution 总和 = state delta)。
//
// Heuristic mapping (prototype 简化):
//   - PropValueDelta target=hp scalar (Tag.HP) + delta < 0 → DamageDealt(actor) + DamageReceived(target)
//   - PropValueDelta target=hp scalar + delta > 0 → HealDone/HealReceived
//   - PropValueDelta target=shield scalar (BuffSource includes "shield") → ShieldAbsorbed
func (rap *RewardAccumPair) AccumulateAfterCommit(ctx *Ctx) {
	for _, p := range ctx.Proposals {
		if p.Rejected {
			continue
		}
		if p.Kind != PropValueDelta {
			continue
		}
		s := p.Scalar
		if s == nil {
			continue
		}
		actor := p.Owner.Player
		// HP-tagged scalar: damage / heal
		if s.Tag == TagHP {
			if p.Delta < 0 {
				dmg := -p.Delta
				if actor >= 0 && actor < 2 {
					rap[actor].DamageDealt += dmg
				}
				if s.Owner.Player >= 0 && s.Owner.Player < 2 {
					rap[s.Owner.Player].DamageReceived += dmg
				}
			} else {
				if actor >= 0 && actor < 2 {
					rap[actor].HealDone += p.Delta
				}
				if s.Owner.Player >= 0 && s.Owner.Player < 2 {
					rap[s.Owner.Player].HealReceived += p.Delta
				}
			}
		}
		// Shield-tagged scalar: shield absorbed (delta < 0 = consume shield)
		if s.Tag == TagShield && p.Delta < 0 {
			absorbed := -p.Delta
			if s.Owner.Player >= 0 && s.Owner.Player < 2 {
				rap[s.Owner.Player].ShieldAbsorbed += absorbed
			}
		}
	}
}

// Tag enum (Scalar.Tag 的 typed 取值,用于 reward attribution dispatch)
const (
	TagNone   = 0
	TagHP     = 1
	TagShield = 2
	TagEnergy = 3
)
