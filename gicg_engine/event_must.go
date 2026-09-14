package engine

import "fmt"

// CardTarget resolves the selected card target from execution frames, including
// nested and deferred effects. It must never fall back to a stale runtime slot.
func (g *Game) CardTarget() (int, int) {
	for i := len(g.eventStack) - 1; i >= 0; i-- {
		f := g.eventStack[i].Current
		if f.HasCardTarget {
			return f.CardTargetPlayer, f.CardTargetChar
		}
	}
	g.FailRule(fmt.Errorf("Target.CardTarget requires a selected card target"), -1)
	return -1, -1
}

// MustCurrentEvent 返回当前事件帧顶,栈空时 panic。
//
// 契约:actor 视角解析(DealDamage / Heal / GainEnergy / ConsumeEnergy /
// resolveTargetHP / invoke_skill 的目标解析与伤害归属)必须发生在显式
// 事件帧内 — 调用方先 PushEvent actor 帧。空栈下 currentEvent() 静默
// 返回零值帧(Player=0),效果全部以 P0 视角结算,即 run-150 回合末
// 友伤 bug 类;fail-loud 在消费端把这类编程错误显式暴露。
//
// 合法的零值帧站点(Defer / DeferAction / DrainDeferred / WriteCounter
// 继承门)仍走 currentEvent(),不受本契约约束。
func (g *Game) MustCurrentEvent(site string) EventFrame {
	if len(g.eventStack) == 0 {
		panic(fmt.Errorf("%s: event stack empty — actor 视角无法解析,调用方必须先 PushEvent actor 帧", site))
	}
	return g.eventStack[len(g.eventStack)-1].Current
}
