package tests

// Support zone lifecycle spike — 锁定 PlayerState.Supports 行为 +
// remove_support 幂等 + count_support 读取 + on_support_remove fire。
//
// 用 派蒙(5448 / 支援牌 / cost match=3 / active=2)做 fixture。
// fire HookCardPlay 模拟入场 → fire HookRoundStart 模拟回合开始触发。
// remove_support / count_support 走 lua eval 跑(走 GoFunc 闭包真路径,
// 与 production DSL 调用路径一致;参考 specialty_ctx_spike_test.go 模式)。

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// fireCardPlay fires HookCardPlay for (player, cardRef). Priority 2000
// engine hook pushes into Supports;DSL on_card_play sets 派蒙_active=2.
func fireCardPlay(g *engine.Game, player, cardRef int) {
	ctx := &engine.EventContext{ActorPlayer: player, CardRef: cardRef}
	g.FireEventHooks(engine.HookCardPlay, ctx)
}

// fireRoundStart fires HookRoundStart with ActorPlayer=player; DSL
// makeHookFn binds rt.CurrentContextPlayer to ctx.ActorPlayer so
// 派蒙 lua's context_player() returns player.
func fireRoundStart(g *engine.Game, player int) {
	ctx := &engine.EventContext{ActorPlayer: player}
	g.FireEventHooks(engine.HookRoundStart, ctx)
}

func TestSupportEntryOccupiesSlot(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]
	if paimon == nil {
		t.Fatalf("派蒙 not in test pool")
	}

	fireCardPlay(env.G, 0, paimon.Ref)

	got := env.G.Players[0].Supports
	if len(got) != 1 {
		t.Fatalf("Supports len = %d, want 1", len(got))
	}
	if got[0].Ref != paimon.Ref {
		t.Errorf("Supports[0].Ref = %d, want 派蒙=%d", got[0].Ref, paimon.Ref)
	}
}

func TestSupportCapacityCap(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]

	// 满 4 槽位(任意 ref 填充,这里复用派蒙 ref)
	env.G.Players[0].Supports = make([]engine.SupportInst, engine.MaxSupportSlots)
	for i := range env.G.Players[0].Supports {
		env.G.Players[0].Supports[i] = engine.SupportInst{Ref: paimon.Ref, ActivatedAt: 1}
	}

	ctx := &engine.EventContext{
		ActorPlayer: 0,
		CardRef:     paimon.Ref,
		ActionKind:  engine.ActionCard,
		Playable:    true,
	}
	env.G.FireEventHooks(engine.HookActionCheck, ctx)

	if ctx.Playable {
		t.Errorf("派蒙 with Supports full (n=%d) → Playable=true, want false",
			engine.MaxSupportSlots)
	}

	// 验证 P1 不受 P0 满影响(per-player cap)
	ctx2 := &engine.EventContext{
		ActorPlayer: 1,
		CardRef:     paimon.Ref,
		ActionKind:  engine.ActionCard,
		Playable:    true,
	}
	env.G.FireEventHooks(engine.HookActionCheck, ctx2)
	if !ctx2.Playable {
		t.Errorf("派蒙 for P1 with P0 supports full → Playable=false, want true (per-player cap)")
	}
}

func TestSupportRemoveOnZero(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]

	fireCardPlay(env.G, 0, paimon.Ref)
	if got := len(env.G.Players[0].Supports); got != 1 {
		t.Fatalf("after entry: Supports=%d, want 1", got)
	}

	// Round 1 start → active=2→1, Supports 仍有
	fireRoundStart(env.G, 0)
	if got := len(env.G.Players[0].Supports); got != 1 {
		t.Errorf("after round 1: Supports=%d, want 1 (active=1 not yet expired)", got)
	}

	// Round 2 start → active=1→0,触发 remove_support
	fireRoundStart(env.G, 0)
	if got := len(env.G.Players[0].Supports); got != 0 {
		t.Errorf("after round 2 (active depleted): Supports=%d, want 0", got)
	}

	// Discard 应含派蒙
	found := false
	for _, c := range env.G.Players[0].Discard {
		if c.Ref == paimon.Ref {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("派蒙 ref %d not in P0 Discard after expiry; Discard=%+v",
			paimon.Ref, env.G.Players[0].Discard)
	}
}

// evalLua runs a small lua snippet against the game's global env.
// Used to drive the remove_support / count_support DSL builtins
// from Go tests (走 GoFunc 闭包真路径,与 production 一致)。
func evalLua(t *testing.T, env *GameEnv, src string) {
	t.Helper()
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("lua eval %q: %v", src, err)
	}
}

func TestRemoveSupportIdempotent(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]

	env.G.Players[0].Supports = []engine.SupportInst{{Ref: paimon.Ref, ActivatedAt: 1}}
	discardBefore := len(env.G.Players[0].Discard)

	// 1st remove via DSL builtin (lua eval)
	evalLua(t, env, fmt.Sprintf("remove_support(0, %d)", paimon.Ref))
	if got := len(env.G.Players[0].Supports); got != 0 {
		t.Errorf("after 1st remove: Supports=%d, want 0", got)
	}
	if got := len(env.G.Players[0].Discard); got != discardBefore+1 {
		t.Errorf("after 1st remove: Discard=%d, want %d", got, discardBefore+1)
	}

	// 2nd remove (no-op — card no longer in Supports)
	evalLua(t, env, fmt.Sprintf("remove_support(0, %d)", paimon.Ref))
	if got := len(env.G.Players[0].Supports); got != 0 {
		t.Errorf("after 2nd remove: Supports=%d, want 0", got)
	}
	if got := len(env.G.Players[0].Discard); got != discardBefore+1 {
		t.Errorf("after 2nd remove: Discard=%d, want %d (no duplicate push)",
			got, discardBefore+1)
	}
}

func TestCountSupport(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]
	envLua := env.RT.Interp.Global

	for n := 0; n <= 3; n++ {
		env.G.Players[0].Supports = make([]engine.SupportInst, n)
		for i := range env.G.Players[0].Supports {
			env.G.Players[0].Supports[i] = engine.SupportInst{Ref: paimon.Ref, ActivatedAt: 1}
		}
		evalLua(t, env, "__cnt = count_support(0)")
		v, ok := envLua.Get("__cnt")
		if !ok {
			t.Fatalf("__cnt not set after count_support call")
		}
		got, _ := v.(int)
		if got != n {
			t.Errorf("count_support(0) with %d entries → %d", n, got)
		}
	}

	// 越界 player → 0
	for _, badP := range []int{-1, 2} {
		evalLua(t, env, fmt.Sprintf("__cnt = count_support(%d)", badP))
		v, _ := envLua.Get("__cnt")
		got, _ := v.(int)
		if got != 0 {
			t.Errorf("count_support(%d) = %d, want 0", badP, got)
		}
	}
}

func TestOnSupportRemoveHook(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]

	type capture struct {
		actorPlayer int
		cardRef     int
	}
	var caps []capture
	env.G.Hooks.Register(engine.Hook{
		Type: engine.HookSupportRemove,
		Fn: func(_ *engine.Game, ctx *engine.EventContext) {
			caps = append(caps, capture{actorPlayer: ctx.ActorPlayer, cardRef: ctx.CardRef})
		},
	})

	env.G.Players[0].Supports = []engine.SupportInst{{Ref: paimon.Ref, ActivatedAt: 1}}
	evalLua(t, env, fmt.Sprintf("remove_support(0, %d)", paimon.Ref))

	if len(caps) != 1 {
		t.Fatalf("HookSupportRemove fired %d times, want 1", len(caps))
	}
	if caps[0].actorPlayer != 0 {
		t.Errorf("ctx.ActorPlayer = %d, want 0", caps[0].actorPlayer)
	}
	if caps[0].cardRef != paimon.Ref {
		t.Errorf("ctx.CardRef = %d, want 派蒙=%d", caps[0].cardRef, paimon.Ref)
	}

	// 不在场的 ref 不触发 hook(no-op + 不 fire)
	evalLua(t, env, fmt.Sprintf("remove_support(0, %d)", paimon.Ref))
	if len(caps) != 1 {
		t.Errorf("second remove_support (no-op) fired hook again, total=%d", len(caps))
	}
}
