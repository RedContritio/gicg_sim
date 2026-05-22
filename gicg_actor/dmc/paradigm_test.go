// paradigm_test.go — DMCParadigm.Configure 单测 + Run loop 单 episode smoke
// (mock InferenceClient + TransitionWriter)。
//
// 完整 e2e 测试见 P1.4 ship Python wiring 后做的 cross-lang integration test。

package dmc

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"math/rand"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"gicg_mono/gicg_actor"
	"gicg_mono/gicg_engine/factory"
)

func TestConfigure_BasicValid(t *testing.T) {
	gameCfg := factory.GameConfig{
		Pools: []string{"v_legacy"},
		Seed:  42,
	}
	gameCfg.Players[0].Chars = []factory.CharDef{{Name: "赤蝶"}}
	gameCfg.Players[1].Chars = []factory.CharDef{{Name: "墨客"}}
	gameSpecBytes, _ := json.Marshal(gameCfg)

	cfg := DMCConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        gameSpecBytes,
			MaxActions:      30,
			MaxEpisodeSteps: 360,
			BaseSeed:        1,
		},
		OpponentMix:      OpponentMix{Random: 0.2, F1D2: 0.3, F1D4: 0.2, Historical: 0.3},
		MyPlayerStrategy: "alternate",
		Epsilon:          0.05,
	}
	cfgBytes, _ := json.Marshal(cfg)

	p := &DMCParadigm{}
	if err := p.Configure(string(cfgBytes)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.OpponentMix.F1D2 != 0.3 {
		t.Errorf("OpponentMix.F1D2 = %v, want 0.3", p.cfg.OpponentMix.F1D2)
	}
	if p.gameCfg.Pools[0] != "v_legacy" {
		t.Errorf("gameCfg.Pools[0] = %q, want v_legacy", p.gameCfg.Pools[0])
	}
}

func TestConfigure_DefaultMyPlayerStrategy(t *testing.T) {
	cfg := DMCConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        json.RawMessage(`{"pools":["v_legacy"],"seed":1,"players":[{"chars":[{"name":"赤蝶"}]},{"chars":[{"name":"墨客"}]}]}`),
			MaxActions:      10,
			MaxEpisodeSteps: 100,
		},
		OpponentMix: OpponentMix{F1D2: 1.0},
		// MyPlayerStrategy omitted — should default to "alternate"
	}
	cfgBytes, _ := json.Marshal(cfg)
	p := &DMCParadigm{}
	if err := p.Configure(string(cfgBytes)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.MyPlayerStrategy != "alternate" {
		t.Errorf("default MyPlayerStrategy = %q, want alternate", p.cfg.MyPlayerStrategy)
	}
}

func TestConfigure_Errors(t *testing.T) {
	validMix := OpponentMix{F1D2: 1.0}
	cases := []struct {
		name    string
		cfg     DMCConfig
		wantSub string
	}{
		{
			name:    "empty game_spec",
			cfg:     DMCConfig{OpponentMix: validMix, BaseActorConfig: gicg_actor.BaseActorConfig{MaxActions: 10, MaxEpisodeSteps: 100}},
			wantSub: "game_spec missing",
		},
		{
			name:    "zero opponent_mix",
			cfg:     DMCConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}},
			wantSub: "opponent_mix weights sum",
		},
		{
			name:    "bad max_actions",
			cfg:     DMCConfig{OpponentMix: validMix, BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 0, MaxEpisodeSteps: 100}},
			wantSub: "max_actions=0",
		},
		{
			name:    "bad max_episode_steps",
			cfg:     DMCConfig{OpponentMix: validMix, BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 0}},
			wantSub: "max_episode_steps=0",
		},
		{
			name:    "unknown strategy",
			cfg:     DMCConfig{OpponentMix: validMix, MyPlayerStrategy: "random", BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}},
			wantSub: "unknown my_player_strategy",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := &DMCParadigm{}
			bs, _ := json.Marshal(tc.cfg)
			err := p.Configure(string(bs))
			if err == nil {
				t.Fatalf("want error containing %q, got nil", tc.wantSub)
			}
			if !strings.Contains(err.Error(), tc.wantSub) {
				t.Errorf("err=%v, want substring %q", err, tc.wantSub)
			}
		})
	}
}

func TestConfigure_EmptyJSON(t *testing.T) {
	p := &DMCParadigm{}
	if err := p.Configure(""); err == nil {
		t.Fatal("Configure(\"\") expected error, got nil")
	}
}

func TestPickActionEpsilonGreedy_Argmax(t *testing.T) {
	logits := []float32{0.1, 0.9, 0.5, 0.0}
	rng := rand.New(rand.NewSource(1))
	// epsilon = 0 → pure argmax
	idx := pickActionEpsilonGreedy(logits, 4, 0.0, rng)
	if idx != 1 {
		t.Errorf("argmax idx = %d, want 1 (logit 0.9)", idx)
	}
}

func TestPickActionEpsilonGreedy_MaskInvalid(t *testing.T) {
	// logits 长度 6 但 only 前 3 是 legal — argmax 限定 nLegal=3。 后面 padded logit
	// 哪怕更高也不应选。
	logits := []float32{0.1, 0.9, 0.5, 100.0, 100.0, 100.0}
	rng := rand.New(rand.NewSource(1))
	idx := pickActionEpsilonGreedy(logits, 3, 0.0, rng)
	if idx != 1 {
		t.Errorf("masked argmax idx = %d, want 1 (logit 0.9), padded logits should not win", idx)
	}
}

func TestPickActionEpsilonGreedy_Explore(t *testing.T) {
	logits := []float32{0.1, 0.9, 0.5}
	rng := rand.New(rand.NewSource(0))
	hits := 0
	const N = 1000
	for i := 0; i < N; i++ {
		idx := pickActionEpsilonGreedy(logits, 3, 1.0, rng) // epsilon=1 → 100% explore
		if idx == 1 {
			hits++
		}
	}
	// uniform random over 3 → ~33% picks idx 1
	if hits < 250 || hits > 420 {
		t.Errorf("epsilon=1 idx=1 hits=%d (expected ~333 of 1000)", hits)
	}
}

func TestPickMePlayer(t *testing.T) {
	if pickMePlayer("fixed_0", 5) != 0 {
		t.Error("fixed_0 should always return 0")
	}
	if pickMePlayer("fixed_1", 5) != 1 {
		t.Error("fixed_1 should always return 1")
	}
	if pickMePlayer("alternate", 0) != 0 || pickMePlayer("alternate", 1) != 1 || pickMePlayer("alternate", 2) != 0 {
		t.Error("alternate should toggle on episode parity")
	}
}

// TestEpisodeStaticTracker 守 static_obs 附带策略:每 episode 第一条 *push* 的
// transition 携带 static,后续 NStatic=0(Python 端 hash cache)。
//
// regression for I29 T-R3 bug:旧逻辑 `if step == 0` 把 static 绑 episode 全局步,
// 而 transition 只在 me 回合 push。 对手先手时 step 0 是 opp 回合不 push,该 episode
// 的 me-transition 永不带 static → assembler cache miss → 丢 episode。 正确策略是
// 绑「第一条被 push 的 transition」,与 step 无关。
func TestEpisodeStaticTracker(t *testing.T) {
	tr := &episodeStaticTracker{}
	static := []int32{10, 20, 30}
	// 第一条 push:附带 static obs。
	if got := tr.take(static); len(got) != 3 {
		t.Fatalf("first take: want static len 3, got len %d", len(got))
	}
	// 后续 push:NStatic=0。
	if got := tr.take(static); got != nil {
		t.Errorf("second take: want nil, got %v", got)
	}
	if got := tr.take(static); got != nil {
		t.Errorf("third take: want nil, got %v", got)
	}
}

// --- runEpisode 终结契约 integration test (T-RR.1) ----------------------------

// startMockInfServerZeros 起 mock InfServer:每 InferRequest 回 maxActions 个 0 logit。
// me 据此 argmax → 恒选 legal action 0(deterministic)。
func startMockInfServerZeros(t *testing.T, maxActions int) (addr string, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				for {
					payload, err := gicg_actor.ReadLengthPrefixed(c)
					if err != nil {
						return
					}
					if _, err := gicg_actor.DecodeInferRequest(payload); err != nil {
						return
					}
					resp := &gicg_actor.InferResponse{
						Status: gicg_actor.InferStatusOK,
						Logits: make([]float32, maxActions),
					}
					enc, err := gicg_actor.EncodeInferResponse(resp)
					if err != nil {
						return
					}
					if _, err := c.Write(enc); err != nil {
						return
					}
				}
			}(conn)
		}
	}()
	return listener.Addr().String(), func() { _ = listener.Close(); wg.Wait() }
}

// startMockTransSinkChan 起 mock transition sink — decode 每条 Transition 推入 channel。
func startMockTransSinkChan(t *testing.T) (addr string, recv <-chan *gicg_actor.Transition, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	ch := make(chan *gicg_actor.Transition, 8192)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				for {
					payload, err := gicg_actor.ReadLengthPrefixed(c)
					if err != nil {
						return
					}
					tr, err := gicg_actor.DecodeTransition(payload)
					if err != nil {
						return
					}
					ch <- tr
				}
			}(conn)
		}
	}()
	return listener.Addr().String(), ch, func() { _ = listener.Close(); wg.Wait() }
}

// TestRunEpisode_EveryEpisodeTerminates 守 episode 终结契约:每个 push 了 ≥1 条
// transition 的 episode 必须恰好有一条 Done=true,且在末尾。
//
// I29 T-RR.1 bug:旧逻辑 done 只在「me 回合 step 后 g.Phase==GameOver」置 true。
// 对手打出致命一击 / MaxEpisodeSteps 截断时,最后一条 me-transition 仍 Done=false,
// 整个 episode 永不带 Done=true → Python assembler 永不 assemble → _buffers 泄漏 +
// episode 数据丢失。 ~半数 episode(对手 final blow)中招。
//
// 两条断言:(1) 每 episode 恰一条 Done=true 且在末尾;(2) 该 Done transition 必须是
// NLegal=0 的 terminal marker。 断言 (2) 让本测试对每个 episode 都能 catch bug —— 旧
// 逻辑下即便 me 自己打死对手,done 也落在真 me-transition(NLegal>0)→ 断言 (2) 失败;
// 故有效性不依赖样本恰好含 opp-final-blow episode。 RED 验证:pre-T-RR.1 代码本测试
// 失败(seed 7 下 episode 1/2/3/11 各 0 条 Done=true)。
func TestRunEpisode_EveryEpisodeTerminates(t *testing.T) {
	const maxActions = 30
	infAddr, stopInf := startMockInfServerZeros(t, maxActions)
	defer stopInf()
	sinkAddr, recv, stopSink := startMockTransSinkChan(t)
	defer stopSink()

	gameCfg := factory.GameConfig{Pools: []string{"v_legacy"}, Seed: 1}
	gameCfg.Players[0].Chars = []factory.CharDef{{Name: "赤蝶"}}
	gameCfg.Players[1].Chars = []factory.CharDef{{Name: "墨客"}}
	gameSpec, _ := json.Marshal(gameCfg)
	cfg := DMCConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec: gameSpec, MaxActions: maxActions, MaxEpisodeSteps: 360, BaseSeed: 1,
		},
		OpponentMix:      OpponentMix{Random: 1.0},
		MyPlayerStrategy: "fixed_0",
		Epsilon:          0.0,
	}
	cfgBytes, _ := json.Marshal(cfg)
	p := &DMCParadigm{}
	if err := p.Configure(string(cfgBytes)); err != nil {
		t.Fatalf("Configure: %v", err)
	}

	infCli := gicg_actor.NewInferenceClient(infAddr, 5*time.Second)
	if err := infCli.Connect(); err != nil {
		t.Fatalf("inf connect: %v", err)
	}
	defer infCli.Close()
	tw := gicg_actor.NewTransitionWriter(sinkAddr, 5*time.Second)
	if err := tw.Connect(); err != nil {
		t.Fatalf("trans connect: %v", err)
	}
	defer tw.Close()

	rng := rand.New(rand.NewSource(7))
	gpD2, err := NewGreedyPlayer("F1", 2, 1)
	if err != nil {
		t.Fatalf("greedy D2: %v", err)
	}
	gpD4, err := NewGreedyPlayer("F1", 4, 2)
	if err != nil {
		t.Fatalf("greedy D4: %v", err)
	}

	const nEpisodes = 12
	for ep := uint32(1); ep <= nEpisodes; ep++ {
		// me=0 fixed; opp random. runEpisode 跑完整 episode。
		if err := p.runEpisode(context.Background(), oppRandom, gpD2, gpD4, rng, infCli, tw, 0, ep, 0); err != nil {
			t.Fatalf("episode %d: %v", ep, err)
		}
	}

	// Drain — 400ms 无新 transition 视为 sink 排空完毕。
	got := map[uint32][]*gicg_actor.Transition{}
	hardDeadline := time.After(8 * time.Second)
	total := 0
collect:
	for {
		select {
		case tr := <-recv:
			got[tr.EpisodeID] = append(got[tr.EpisodeID], tr)
			total++
		case <-time.After(400 * time.Millisecond):
			break collect
		case <-hardDeadline:
			break collect
		}
	}
	if total == 0 {
		t.Fatal("no transitions received")
	}

	for ep, trs := range got {
		doneCount := 0
		for i, tr := range trs {
			if tr.Done {
				doneCount++
				if i != len(trs)-1 {
					t.Errorf("episode %d: Done=true at index %d, not last (len=%d)", ep, i, len(trs))
				}
				// Done transition 必须是 terminal marker — NLegal=0(DMC payload header
				// offset 12:16)。 旧 bug 逻辑把 done 落在真 me-transition(NLegal>0)。
				if len(tr.Payload) < 16 {
					t.Fatalf("episode %d: Done transition payload too short: %d byte", ep, len(tr.Payload))
				}
				if nl := binary.LittleEndian.Uint32(tr.Payload[12:16]); nl != 0 {
					t.Errorf("episode %d: Done transition NLegal=%d, want 0 (terminal marker)", ep, nl)
				}
			}
		}
		if doneCount != 1 {
			t.Errorf("episode %d: %d transitions Done=true, want exactly 1 (n_trans=%d)", ep, doneCount, len(trs))
		}
	}
	t.Logf("episodes=%d total_transitions=%d", len(got), total)
}

// TestRunEpisode_PushFailureNotFatal 守 I29 T-RR.3 audit #5:transition Push 失败
// (socket 抖动 / consumer 死 / 超 transitionWriteTimeout)不致死 actor —— runEpisode
// 返 nil(episode 中止),Run loop 得以继续下个 episode,不可逆减员被消除。
func TestRunEpisode_PushFailureNotFatal(t *testing.T) {
	const maxActions = 30
	infAddr, stopInf := startMockInfServerZeros(t, maxActions)
	defer stopInf()

	gameCfg := factory.GameConfig{Pools: []string{"v_legacy"}, Seed: 1}
	gameCfg.Players[0].Chars = []factory.CharDef{{Name: "赤蝶"}}
	gameCfg.Players[1].Chars = []factory.CharDef{{Name: "墨客"}}
	gameSpec, _ := json.Marshal(gameCfg)
	cfg := DMCConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec: gameSpec, MaxActions: maxActions, MaxEpisodeSteps: 360, BaseSeed: 1,
		},
		OpponentMix:      OpponentMix{Random: 1.0},
		MyPlayerStrategy: "fixed_0",
		Epsilon:          0.0,
	}
	cfgBytes, _ := json.Marshal(cfg)
	p := &DMCParadigm{}
	if err := p.Configure(string(cfgBytes)); err != nil {
		t.Fatalf("Configure: %v", err)
	}

	infCli := gicg_actor.NewInferenceClient(infAddr, 5*time.Second)
	if err := infCli.Connect(); err != nil {
		t.Fatalf("inf connect: %v", err)
	}
	defer infCli.Close()

	// transWri 指向无人监听的端口 → Push lazy-dial 失败(connection refused)。
	tw := gicg_actor.NewTransitionWriter("127.0.0.1:1", 1*time.Second)
	defer tw.Close()

	rng := rand.New(rand.NewSource(7))
	gpD2, err := NewGreedyPlayer("F1", 2, 1)
	if err != nil {
		t.Fatalf("greedy D2: %v", err)
	}
	gpD4, err := NewGreedyPlayer("F1", 4, 2)
	if err != nil {
		t.Fatalf("greedy D4: %v", err)
	}

	// Push 必失败(dead addr)→ runEpisode 应返 nil(actor 存活),非 fatal error。
	if err := p.runEpisode(context.Background(), oppRandom, gpD2, gpD4, rng, infCli, tw, 0, 1, 0); err != nil {
		t.Fatalf("runEpisode should return nil on Push failure (actor must survive), got: %v", err)
	}
}

// TestSampleOpponentKind 守 OpponentMix 权重抽样:纯单权重 → 恒定;混合 → 经验
// 分布匹配权重。 I29 T-R3:对手按 opponent_mix 抽,替代旧硬编码 100% F1-D2。
func TestSampleOpponentKind(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	// 纯 random 权重 → 永远 oppRandom。
	for i := 0; i < 50; i++ {
		if k := sampleOpponentKind(OpponentMix{Random: 1.0}, rng); k != oppRandom {
			t.Fatalf("pure-random mix: got kind %d, want oppRandom", k)
		}
	}
	// 混合权重(权重不和为 1 也应归一化)→ 经验分布大致匹配。
	mix := OpponentMix{Random: 2.0, F1D2: 3.0, F1D4: 2.0, Historical: 3.0}
	counts := map[oppKind]int{}
	const N = 4000
	for i := 0; i < N; i++ {
		counts[sampleOpponentKind(mix, rng)]++
	}
	for _, tc := range []struct {
		kind oppKind
		want float64
	}{
		{oppRandom, 0.2}, {oppF1D2, 0.3}, {oppF1D4, 0.2}, {oppHistorical, 0.3},
	} {
		got := float64(counts[tc.kind]) / N
		if got < tc.want-0.06 || got > tc.want+0.06 {
			t.Errorf("kind %d: empirical %.3f, want ~%.2f", tc.kind, got, tc.want)
		}
	}
}
