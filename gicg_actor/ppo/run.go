// run.go — PPO Run loop:on-policy rollout + temperature sampling + value head。
//
// Reuses dmc package helpers(BuildInferRequest / ComputeStaticHash / GreedyPlayer)— obs
// schema 跨 paradigm 统一(per memory: 5 paradigm 完全统一 backbone)。
//
// Per episode:
// 1. factory.NewGame + compute static_obs + hash
// 2. Per step:
//    · acting==me: BuildInferRequest → InferCli.Request → (logits, value) →
//      temperature sample → chosen action; compute log_prob of chosen
//    · acting==opp: rollout_opponent spec dispatch(random / F{X}-D{Y});'self' P2.X 后续
//    · g.Step(chosen)
//    · if me turn: encode + push PPO transition with reward=terminalReward / log_prob /
//      value / done
// 3. Episode end → push terminal transition with reward = sign(winner)

package ppo

import (
	"context"
	"fmt"
	"math"
	"math/rand"
	"strconv"
	"strings"

	"gicg_mono/gicg_actor"
	"gicg_mono/gicg_actor/dmc"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
	"gicg_mono/gicg_engine/interp"
)

// Run — replaces P2.1 stub。 完整 episode loop。
func (p *PPOParadigm) Run(
	ctx context.Context,
	actorID int,
	infCli *gicg_actor.InferenceClient,
	transWri *gicg_actor.TransitionWriter,
) error {
	if infCli == nil {
		return fmt.Errorf("PPOParadigm.Run: inference client required(actor=%d)", actorID)
	}
	if transWri == nil {
		return fmt.Errorf("PPOParadigm.Run: transition writer required(actor=%d)", actorID)
	}

	rng := rand.New(rand.NewSource(p.cfg.BaseSeed + int64(actorID)*1009))
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
		if err := p.runEpisode(ctx, rng, infCli, transWri, clientID, episodeID, mePlayer); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("actor=%d ep=%d: %w", actorID, episodeID, err)
		}
	}
}

// pickMePlayer mirror dmc 同名 fn(my_player_strategy:alternate/fixed_0/fixed_1)。
func pickMePlayer(strategy string, episodeID int) int {
	switch strategy {
	case "fixed_0":
		return 0
	case "fixed_1":
		return 1
	default:
		return episodeID & 1
	}
}

// oppActionFn — opp 端 select action callback。
type oppActionFn func(g *engine.Game, rt *interp.Runtime) (int, error)

// buildOppMover parses rollout_opponent spec into a callable。
func buildOppMover(spec string, seed int64) (oppActionFn, error) {
	rng := rand.New(rand.NewSource(seed))
	switch spec {
	case "":
		return nil, fmt.Errorf("rollout_opponent empty")
	case "self":
		return nil, fmt.Errorf("rollout_opponent='self' not supported in P2.X — use 'random' or 'F{i}-D{j}'")
	case "random":
		return func(g *engine.Game, _ *interp.Runtime) (int, error) {
			actions := g.GetLegalActions()
			if len(actions) == 0 {
				return -1, fmt.Errorf("opp random: no legal actions")
			}
			return rng.Intn(len(actions)), nil
		}, nil
	}
	parts := strings.Split(spec, "-")
	if len(parts) < 2 || !strings.HasPrefix(parts[0], "F") || !strings.HasPrefix(parts[1], "D") {
		return nil, fmt.Errorf("unknown rollout_opponent %q (expected 'random' / 'F{i}-D{j}')", spec)
	}
	features := parts[0]
	depth, err := strconv.Atoi(parts[1][1:])
	if err != nil {
		return nil, fmt.Errorf("bad depth in %q: %w", spec, err)
	}
	gp, err := dmc.NewGreedyPlayer(features, depth, seed)
	if err != nil {
		return nil, fmt.Errorf("build GreedyPlayer(%s, %d): %w", features, depth, err)
	}
	return func(_ *engine.Game, rt *interp.Runtime) (int, error) {
		return gp.SelectAction(rt)
	}, nil
}

// runEpisode — 单 episode loop。
func (p *PPOParadigm) runEpisode(
	ctx context.Context,
	rng *rand.Rand,
	infCli *gicg_actor.InferenceClient,
	transWri *gicg_actor.TransitionWriter,
	clientID, episodeID uint32,
	me int,
) error {
	gameCfg := p.gameCfg
	gameCfg.Seed = int64(clientID)*1_000_003 + int64(episodeID)*7919
	h, err := factory.NewGame(gameCfg)
	if err != nil {
		return fmt.Errorf("factory.NewGame: %w", err)
	}
	g := h.Game
	rt := h.RT

	oppMover, err := buildOppMover(p.cfg.RolloutOpponent, p.cfg.BaseSeed+int64(clientID)*7919+int64(episodeID))
	if err != nil {
		return fmt.Errorf("build opp mover: %w", err)
	}

	staticInt32 := g.BuildStaticObs()
	staticHash := dmc.ComputeStaticHash(staticInt32)
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
		var preStepDyn []float32
		var preStepRefs []int64
		var preStepPay []float32
		var preStepNLegal int
		var preStepValue float32
		var preStepLogProb float32

		if acting == me {
			reqID++
			req := dmc.BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
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
			chosen, preStepLogProb = sampleActionTemperature(resp.Logits, len(actions), p.cfg.Temperature, rng)
			if chosen < 0 || chosen >= len(actions) {
				return fmt.Errorf("action selection produced out-of-range idx=%d (n=%d)", chosen, len(actions))
			}
			// refs/pay slice 到前 nlegal 段 — inference 仍走 padded(网络 forward 要 fixed
			// (max_actions, ...) shape),但 transition payload 只载 nlegal 行(I29 P2 root cause
			// — buffer per-trans mem ~10x 降)。
			preStepDyn = req.DynObs
			preStepRefs = req.Refs[:len(actions)*3]
			preStepPay = req.Pay[:len(actions)*dmc.DiceColorCount]
			preStepNLegal = len(actions)
			if len(resp.Value) > 0 {
				preStepValue = resp.Value[0]
			}
			pushTrans = true
		} else {
			c, err := oppMover(g, rt)
			if err != nil {
				return fmt.Errorf("opp step=%d: %w", step, err)
			}
			chosen = c
		}

		g.Step(chosen)

		if pushTrans {
			done := g.Phase == engine.PhaseGameOver
			reward := float32(0)
			if done {
				reward = terminalReward(g, me)
			}
			var staticForTrans []int32
			if step == 0 {
				staticForTrans = staticInt32
			}
			payload := EncodePpoTransitionPayload(
				uint32(chosen), step, reward, preStepLogProb, preStepValue, preStepNLegal,
				preStepDyn, preStepRefs, preStepPay, staticForTrans, staticHash,
			)
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
	return 0.0
}

// sampleActionTemperature — temperature softmax sampling over legal logits。
// T=0 → argmax + log_prob=0(deterministic);T>0 → softmax(logits/T) → sample。
// 返 (chosen idx, log_prob f32)。
func sampleActionTemperature(logits []float32, nLegal int, temperature float32, rng *rand.Rand) (int, float32) {
	if nLegal <= 0 {
		return -1, 0
	}
	limit := nLegal
	if limit > len(logits) {
		limit = len(logits)
	}
	if temperature == 0 {
		bestIdx := 0
		bestVal := float32(math.Inf(-1))
		for i := 0; i < limit; i++ {
			if logits[i] > bestVal {
				bestVal = logits[i]
				bestIdx = i
			}
		}
		return bestIdx, 0.0
	}
	// Softmax(logits / T) over legal slice with numerical stability(subtract max)。
	maxL := float32(math.Inf(-1))
	for i := 0; i < limit; i++ {
		v := logits[i] / temperature
		if v > maxL {
			maxL = v
		}
	}
	expSum := float32(0)
	exps := make([]float32, limit)
	for i := 0; i < limit; i++ {
		e := float32(math.Exp(float64(logits[i]/temperature - maxL)))
		exps[i] = e
		expSum += e
	}
	r := rng.Float32() * expSum
	cumsum := float32(0)
	for i := 0; i < limit; i++ {
		cumsum += exps[i]
		if r <= cumsum {
			prob := exps[i] / expSum
			return i, float32(math.Log(float64(prob)))
		}
	}
	prob := exps[limit-1] / expSum
	return limit - 1, float32(math.Log(float64(prob)))
}
