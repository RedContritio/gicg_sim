// paradigm.go — DMC Paradigm impl(adapter.go Paradigm interface 实现)。
//
// Configure 接 JSON cfg(game spec + opp 配置 + max_actions / max_episode_steps),Run
// 跑真 episode loop:
//   - 每 episode 调 factory.NewGame(gameSpec) 构造 engine instance(native Go,~ms 级 init)
//   - 计算 static_hash(每 episode 一次,跨 turn 不变)
//   - 主循环:
//     · acting player == me: BuildInferRequest → InferenceClient.Request → 解码 chosen
//       action idx → engine.Step → push transition
//     · acting player == opp: GreedyPlayer.SelectAction(F1-D2/D4)→ engine.Step
//     · engine.Phase == GameOver: push final transition + break
//   - episode 完结 → new engine instance + 继续(每 episode new engine,P3 优化 reuse)

package dmc

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"sync"

	"gicg_mono/gicg_actor"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

// DMCConfig — Configure() JSON schema(Python side ParadigmConfigJSON 必须符合)。
//
// GameSpec 走 factory.GameConfig 同 wire 格式(JSON 子树,Configure 把它再 unmarshal 一次到
// factory.GameConfig)— 这样 Python 单一 source of truth 是 ScenarioCfg → factory.GameConfig
// JSON,Go 透传 GameSpec 子树即可,无需第二份 schema。
//
// OppFeatures + OppDepth 配 GreedyPlayer(F1-F5 × D1-D4)。 MyPlayerStrategy 决定 me 在每
// episode 是固定 0 / 固定 1 / 随机轮换(`alternate`),production 默认 `alternate` 防
// position bias。
type DMCConfig struct {
	GameSpec         json.RawMessage `json:"game_spec"`
	OppFeatures      string          `json:"opp_features"`
	OppDepth         int             `json:"opp_depth"`
	MaxActions       int             `json:"max_actions"`
	MaxEpisodeSteps  int             `json:"max_episode_steps"`
	MyPlayerStrategy string          `json:"my_player_strategy"` // "alternate" | "fixed_0" | "fixed_1"
	BaseSeed         int64           `json:"base_seed"`
	// Epsilon — ε-greedy exploration prob (0.0 = pure argmax). DMC 默认 ~0.05.
	Epsilon float32 `json:"epsilon"`
}

// DMCParadigm implements gicg_actor.Paradigm。
type DMCParadigm struct {
	cfg     DMCConfig
	gameCfg factory.GameConfig // pre-parsed from cfg.GameSpec for fast-path episode start
}

func (p *DMCParadigm) Name() string {
	return "dmc"
}

// Configure 反序列化 DMCConfig + 预解 GameSpec → factory.GameConfig,fail-loud 任何
// schema / 字段错误。 必须在 actor goroutine spawn 之前调一次。
func (p *DMCParadigm) Configure(jsonCfg string) error {
	if jsonCfg == "" {
		return fmt.Errorf("DMCParadigm.Configure: empty JSON config")
	}
	var c DMCConfig
	if err := json.Unmarshal([]byte(jsonCfg), &c); err != nil {
		return fmt.Errorf("DMCParadigm.Configure: unmarshal DMCConfig: %w", err)
	}
	if len(c.GameSpec) == 0 || string(c.GameSpec) == "null" {
		return fmt.Errorf("DMCParadigm.Configure: game_spec missing")
	}
	if c.OppFeatures == "" {
		return fmt.Errorf("DMCParadigm.Configure: opp_features missing")
	}
	if c.OppDepth < 1 || c.OppDepth > 4 {
		return fmt.Errorf("DMCParadigm.Configure: opp_depth=%d not in [1,4]", c.OppDepth)
	}
	if c.MaxActions <= 0 {
		return fmt.Errorf("DMCParadigm.Configure: max_actions=%d must be positive", c.MaxActions)
	}
	if c.MaxEpisodeSteps <= 0 {
		return fmt.Errorf("DMCParadigm.Configure: max_episode_steps=%d must be positive", c.MaxEpisodeSteps)
	}
	switch c.MyPlayerStrategy {
	case "alternate", "fixed_0", "fixed_1":
	case "":
		c.MyPlayerStrategy = "alternate"
	default:
		return fmt.Errorf("DMCParadigm.Configure: unknown my_player_strategy=%q", c.MyPlayerStrategy)
	}
	var gameCfg factory.GameConfig
	if err := json.Unmarshal(c.GameSpec, &gameCfg); err != nil {
		return fmt.Errorf("DMCParadigm.Configure: unmarshal game_spec: %w", err)
	}
	p.cfg = c
	p.gameCfg = gameCfg
	return nil
}

// Run — actor goroutine 主循环。 每 episode 算独立 game,直到 ctx.Done() 才退出 outer loop。
func (p *DMCParadigm) Run(ctx context.Context, actorID int, infCli *gicg_actor.InferenceClient, transWri *gicg_actor.TransitionWriter) error {
	// Per-actor seed (derived) — 决定 opp tie-break + my-player alternation + ε-greedy explore
	rng := rand.New(rand.NewSource(p.cfg.BaseSeed + int64(actorID)*1009))
	gp, err := NewGreedyPlayer(p.cfg.OppFeatures, p.cfg.OppDepth, p.cfg.BaseSeed+int64(actorID)*7919)
	if err != nil {
		return fmt.Errorf("actor=%d: build greedy player: %w", actorID, err)
	}

	clientID := uint32(actorID)
	var episodeID uint32

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}
		episodeID++
		mePlayer := pickMePlayer(p.cfg.MyPlayerStrategy, int(episodeID))
		if err := p.runEpisode(ctx, gp, rng, infCli, transWri, clientID, episodeID, mePlayer); err != nil {
			// ctx cancel mid-episode 不算 fatal — outer loop 重新检查 ctx.Done()
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("actor=%d ep=%d: %w", actorID, episodeID, err)
		}
	}
}

// pickActionEpsilonGreedy — DMC policy: ε prob uniform random over legal, else argmax over
// legal logits。 logits 长度应是 MaxActions(由 InfServer 端 batch padding 决定);只前 nLegal
// 个是合法 action,后面 pad 行 mask 掉。
func pickActionEpsilonGreedy(logits []float32, nLegal int, epsilon float32, rng *rand.Rand) int {
	if nLegal <= 0 {
		return -1
	}
	if epsilon > 0 && rng.Float32() < epsilon {
		return rng.Intn(nLegal)
	}
	bestIdx := 0
	bestVal := float32(-1e30)
	limit := nLegal
	if limit > len(logits) {
		limit = len(logits)
	}
	for i := 0; i < limit; i++ {
		if logits[i] > bestVal {
			bestVal = logits[i]
			bestIdx = i
		}
	}
	return bestIdx
}

func pickMePlayer(strategy string, episodeID int) int {
	switch strategy {
	case "fixed_0":
		return 0
	case "fixed_1":
		return 1
	default: // "alternate" — episode parity
		return episodeID & 1
	}
}

// runEpisode 跑一个完整 episode。 me 决定 actor (network) 的 player_idx,opp 是另一边。
func (p *DMCParadigm) runEpisode(
	ctx context.Context,
	gp *GreedyPlayer,
	rng *rand.Rand,
	infCli *gicg_actor.InferenceClient,
	transWri *gicg_actor.TransitionWriter,
	clientID, episodeID uint32,
	me int,
) error {
	// Per-episode seed: derive from clientID + episodeID so multi-actor / multi-episode
	// 分布唯一(seed collision = duplicate game = wasted compute)
	gameCfg := p.gameCfg
	gameCfg.Seed = int64(clientID)*1_000_003 + int64(episodeID)*7919
	h, err := factory.NewGame(gameCfg)
	if err != nil {
		return fmt.Errorf("factory.NewGame: %w", err)
	}
	g := h.Game
	rt := h.RT

	// static_obs 缓存(整 episode 不变)+ hash 派生。 第一次 acting==me request 携带
	// raw static int32 数组喂 InfServer cache,后续 request Static=nil(server 走
	// hash lookup)。 InfServer 同 scenario 多 actor 共享 cache 命中率高,后续 N-1 个
	// request 节省 ~12 KB/req(static_obs 平均尺寸)。
	staticInt32 := g.BuildStaticObs()
	staticHash := ComputeStaticHash(staticInt32)
	staticSentThisEpisode := false

	var step uint32
	var reqID uint32
	for step = 0; step < uint32(p.cfg.MaxEpisodeSteps); step++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if g.Phase == engine.PhaseGameOver {
			break
		}
		acting := g.ActingPlayer()
		var chosen int
		var pushTrans bool
		if acting == me {
			if infCli == nil {
				return fmt.Errorf("inference client nil on actor turn")
			}
			reqID++
			req := BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
			if !staticSentThisEpisode {
				req.Static = staticInt32
				staticSentThisEpisode = true
			}
			resp, err := infCli.Request(req)
			if err != nil {
				return fmt.Errorf("inference request step=%d: %w", step, err)
			}
			if resp.Status != gicg_actor.InferStatusOK {
				return fmt.Errorf("inference status err: %s", resp.ErrMsg)
			}
			actions := g.GetLegalActions()
			chosen = pickActionEpsilonGreedy(resp.Logits, len(actions), p.cfg.Epsilon, rng)
			if chosen < 0 || chosen >= len(actions) {
				return fmt.Errorf("action selection produced out-of-range idx=%d (n=%d)", chosen, len(actions))
			}
			pushTrans = transWri != nil
		} else {
			c, err := gp.SelectAction(rt)
			if err != nil {
				return fmt.Errorf("opp greedy step=%d: %w", step, err)
			}
			chosen = c
		}

		// reward 计 step pre/post(only for actor's own steps);DMC reward 用 terminal 0/+1/-1
		// + 中途 0,所以 transition push 时 reward=0 — final transition 用 winner 推。
		dynInt32 := g.BuildDynamicObs(me)
		dynF32 := make([]float32, len(dynInt32))
		for i, v := range dynInt32 {
			dynF32[i] = float32(v)
		}

		g.Step(chosen)

		if pushTrans {
			done := g.Phase == engine.PhaseGameOver
			reward := float32(0)
			if done {
				reward = terminalReward(g, me)
			}
			payload := EncodeMinimalTransitionPayload(dynF32, uint32(chosen), step, reward)
			tx := &gicg_actor.Transition{
				ClientID:  clientID,
				EpisodeID: episodeID,
				Step:      step,
				Done:      done,
				Payload:   payload,
			}
			if err := transWri.Push(tx); err != nil {
				return fmt.Errorf("transition push step=%d: %w", step, err)
			}
		}
	}
	return nil
}

func terminalReward(g *engine.Game, me int) float32 {
	if g.Winner == me {
		return 1.0
	}
	if g.Winner == 1-me {
		return -1.0
	}
	return 0.0 // draw / timeout
}

// 一次性 register(package init 触发)+ mutex 防 重复 import 时 race。 Real-world 单 process
// 单一 init() 调用,但 test helper 可能多次 Reset → 重新 register。
var (
	registerOnce sync.Once
)

func init() {
	registerOnce.Do(func() {
		gicg_actor.RegisterParadigm("dmc", &DMCParadigm{})
	})
}
