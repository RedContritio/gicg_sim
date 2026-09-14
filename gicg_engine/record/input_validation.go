package record

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

func (a Action) validateInput() error {
	i := a.Input
	if i == nil {
		if a.Kind == ActReroll {
			return fmt.Errorf("reroll requires exact input")
		}
		return nil
	} // legacy record: semantic matching only
	if a.Kind == ActReroll {
		if i.RerollColor < 0 || i.RerollColor > engine.DiceColorCount || i.RerollCount < 0 ||
			(i.RerollColor == engine.DiceColorCount && i.RerollCount != 0) || i.DicePayment != [engine.DiceColorCount]int8{} {
			return fmt.Errorf("invalid dice selection")
		}
	} else if i.RerollColor != 0 || i.RerollCount != 0 {
		return fmt.Errorf("dice selection on non-reroll action")
	}
	for _, n := range i.DicePayment {
		if n < 0 {
			return fmt.Errorf("negative dice payment")
		}
	}
	if a.Kind == ActCard || a.Kind == ActTune {
		if i.HandIndex < 0 {
			return fmt.Errorf("negative hand index")
		}
	} else if i.HandIndex != -1 {
		return fmt.Errorf("hand index on non-card action")
	}
	if i.Forced && a.Kind != ActSwitch {
		return fmt.Errorf("forced flag on non-switch action")
	}
	if i.HasSupportTarget {
		if i.TargetBuff != 0 {
			return fmt.Errorf("buff position on support target")
		}
		if i.HasBuffTarget || i.HasTarget || a.Kind != ActCard || i.TargetPlayer != a.Player || i.TargetChar != -1 || i.TargetSupport < 0 || i.TargetSupport >= engine.MaxSupportSlots {
			return fmt.Errorf("invalid support replacement")
		}
	} else if i.TargetSupport != 0 {
		return fmt.Errorf("support slot without support target")
	} else if i.HasBuffTarget {
		if i.HasTarget || a.Kind != ActCard || i.TargetPlayer < 0 || i.TargetPlayer > 1 || i.TargetChar != -1 || i.TargetBuff < 0 {
			return fmt.Errorf("invalid buff target")
		}
	} else if i.TargetBuff != 0 {
		return fmt.Errorf("buff position without buff target")
	} else if i.HasTarget {
		if a.Kind != ActCard || i.TargetPlayer < 0 || i.TargetPlayer > 1 || i.TargetChar < 0 || i.TargetChar >= engine.ObsMaxChars {
			return fmt.Errorf("invalid card target")
		}
	} else if i.TargetPlayer != 0 || i.TargetChar != 0 {
		return fmt.Errorf("target without has_target")
	}
	if a.Kind == ActTune {
		if i.TuneSourceColor < 0 || i.TuneSourceColor >= engine.DiceColorOmni {
			return fmt.Errorf("invalid tune source")
		}
	} else if i.TuneSourceColor != 0 {
		return fmt.Errorf("tune source on non-tune action")
	}
	return nil
}
