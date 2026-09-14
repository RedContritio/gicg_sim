package engine

// Action struct and top-level GetLegalActions dispatcher. Per-kind
// enumeration helpers (enumerateSkills / Cards / Switches / Tunes +
// selectActiveActions / forcedSwitchActions) live in action_enum.go.
// Step and target-resolution live in action_step.go. execute* (per-kind
// executors + dice payment) live in action_execute.go.

type Action struct {
	Kind      ActionKind
	PlayerIdx int
	Index     int  // 技能索引 / 手牌索引 / 角色索引(switch) / 手牌索引(tune)
	Forced    bool // 强制切换（死亡/超载），不消耗骰子,不翻转行动权

	// Dice payment: 该 action 消耗的骰子 multiset,按 DiceColor
	// 索引。仅当 Kind 是 Skill/Card/Switch 时有意义。
	DicePayment [DiceColorCount]int8

	// AppliedMods is the set of prepare-phase hook IDs that
	// successfully called cost_mod for this candidate during
	// enumeration. Restored into EventContext.AppliedMods at
	// execution time so consumer hooks can query was_applied.
	// nil is treated as empty.
	AppliedMods map[int]bool

	// Card-play target (joint action style): when the card requires a
	// target (e.g. heal cards), the target is baked into the action
	// rather than going through a separate STEP_NEED_TARGET pending
	// state.
	HasTarget        bool
	TargetPlayer     int
	TargetChar       int
	HasBuffTarget    bool
	TargetBuff       int // position in live creation-ordered Buffs, never a raw ID
	HasSupportTarget bool
	TargetSupport    int // replacement slot in own support zone

	// Tune source: which dice color to convert to the char element.
	// Only meaningful when Kind == ActionTune.
	TuneSourceColor int
	RerollColor     int // 0..7 selects a count; DiceColorCount confirms
}

// GetLegalActions enumerates legal actions for the current acting
// player. Phase IV: dice-based cost enumeration. For each skill/card/
// switch candidate that passes action_check, enumerate all distinct
// dice payment multisets; for target-requiring cards, enumerate
// (target × payment) as joint compound actions. Tune actions convert
// 1 non-active-element non-omni die into the active char's element
// at the cost of 1 hand card.
//
// Cost modification lifecycle per candidate:
//  1. ctx.Cost is set to the declared DiceCost
//  2. HookActionPrepare fires; DSL hooks mutate via cost_mod, which
//     auto-records their hook ID in ctx.AppliedMods
//  3. HookActionCheck fires; DSL hooks set ctx.Playable
//  4. ctx.Cost is clamped to non-negative
//  5. Payment variants are enumerated from the effective cost
//  6. ctx.AppliedMods is baked into each enumerated Action
func (g *Game) GetLegalActions() []Action {
	g.RequireHealthy()
	if g.Phase == PhaseGameOver {
		return nil
	}
	if g.PendingDice != nil {
		return g.diceSelectionActions()
	}

	// 首回合选择出战角色：所有角色可选
	if g.Phase == PhaseSelectActive {
		return g.selectActiveActions(g.Turn)
	}

	// 回合间暂停：自动推进到下一回合
	if g.Phase == PhaseRoundStart {
		g.NewRound()
	}

	if g.PendingAction != nil && g.PendingAction.Kind == ActionSwitch {
		return g.forcedSwitchActions(g.PendingAction.PlayerIdx)
	}

	// Legacy PendingCardTarget path: joint-action mode no longer
	// generates these, but keep the branch as a safety net for any
	// code path that still sets PendingCardTarget directly.
	if g.PendingCardTarget != nil {
		return g.cardTargetActions(g.PendingCardTarget)
	}
	if g.Phase != PhaseAction {
		return nil
	}

	pi := g.ActingPlayer()
	p := &g.Players[pi]

	if p.ActiveChar < 0 || p.ActiveChar >= len(p.Chars) {
		return []Action{{Kind: ActionEndTurn, PlayerIdx: pi}}
	}

	rt := g.Extra.(DicePoolProvider)

	// Read the player's dice pool (8 slots: fire..dendro, omni).
	var pool [DiceColorCount]int
	for c := 0; c < DiceColorCount; c++ {
		pool[c] = g.Counters[rt.DiceCounterID(pi, c)].Value
	}

	var actions []Action
	actions = g.enumerateSkills(pi, pool, rt, actions)
	actions = g.enumerateCards(pi, pool, rt, actions)
	actions = g.enumerateSwitches(pi, pool, actions)
	actions = g.enumerateTunes(pi, pool, actions)

	// End turn is always legal.
	actions = append(actions, Action{
		Kind:      ActionEndTurn,
		PlayerIdx: pi,
	})

	return actions
}
