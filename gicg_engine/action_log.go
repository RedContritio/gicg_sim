package engine

// ActionInput records player choices, excluding derived hook IDs and costs.
// Skill/card names in the human header provide semantic identity; HandIndex
// disambiguates duplicate card instances without persisting registry IDs.
type ActionInput struct {
	DicePayment      [DiceColorCount]int8 `json:"payment"`
	HandIndex        int                  `json:"hand_index"`
	Forced           bool                 `json:"forced"`
	HasTarget        bool                 `json:"has_target"`
	TargetPlayer     int                  `json:"target_player"`
	TargetChar       int                  `json:"target_char"`
	HasBuffTarget    bool                 `json:"has_buff_target,omitempty"`
	TargetBuff       int                  `json:"target_buff,omitempty"`
	HasSupportTarget bool                 `json:"has_support_target,omitempty"`
	TargetSupport    int                  `json:"target_support,omitempty"`
	TuneSourceColor  int                  `json:"tune_source_color"`
	RerollColor      int                  `json:"reroll_color,omitempty"`
	RerollCount      int                  `json:"reroll_count,omitempty"`
}

func InputForAction(a Action) ActionInput {
	i := ActionInput{DicePayment: a.DicePayment, HandIndex: -1, Forced: a.Forced,
		HasTarget: a.HasTarget, TargetPlayer: a.TargetPlayer, TargetChar: a.TargetChar,
		HasBuffTarget: a.HasBuffTarget, TargetBuff: a.TargetBuff, TuneSourceColor: a.TuneSourceColor}
	i.HasSupportTarget, i.TargetSupport = a.HasSupportTarget, a.TargetSupport
	if a.Kind == ActionReroll {
		i.RerollColor, i.RerollCount = a.RerollColor, a.Index
	}
	if a.Kind == ActionCard || a.Kind == ActionTune {
		i.HandIndex = a.Index
	}
	return i
}

func (g *Game) logAction(a Action) {
	if g.Log == nil {
		return
	}
	g.Log.NextStep()
	pi := a.PlayerIdx
	fields := map[string]interface{}{"input": InputForAction(a)}
	kind := ""
	switch a.Kind {
	case ActionReroll:
		kind = "action_reroll"
	case ActionSkill:
		kind = "action_skill"
		fields["skill_id"] = a.Index
	case ActionCard, ActionTune:
		kind = "action_card"
		if a.Kind == ActionTune {
			kind = "action_tune"
		}
		fields["card_ref"] = g.Players[pi].Hand[a.Index].Ref
		fields["hand_idx"] = a.Index
		if a.HasTarget {
			fields["target_player"], fields["target_char"] = a.TargetPlayer, a.TargetChar
		}
	case ActionSwitch:
		kind = "action_switch"
		fields["target_char"] = a.Index
	case ActionEndTurn:
		kind = "action_end_turn"
	}
	if kind != "" {
		g.Log.Append(g, kind, pi, g.Players[pi].ActiveChar, fields)
	}
}
