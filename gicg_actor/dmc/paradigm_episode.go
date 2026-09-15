// paradigm_episode.go — 单个 episode 的执行循环 + 终局 reward。
//
// 从 paradigm.go 拆出(单文件行数上限)。 runEpisode 是 DMC actor 的热路径:每
// episode 重置 engine 动态状态 → 交替 me/opp 行动 → 累积 transition → 一次性
// PushBatch。 static_obs 只在本 episode 第一条被 push 的 transition 上附带
// (episodeStaticTracker),之后走 Python 侧 hash cache。

package dmc

import (
	"context"
	"fmt"
	"math/rand"
	"os"

	"gicg_mono/gicg_actor"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

// episodeStaticTracker 跟踪 episode 的 static_obs 是否已附带到某条已 push 的
// transition。 每 episode 第一条被 push 的 transition 携带 raw static int32,
// 后续 take 返 nil(NStatic=0,Python assembler 走 hash cache)。
//
// 不能用 episode step 判定 —— transition 只在 me 回合 push,对手先手时 step 0
// 不 push,static 会丢(assembler cache miss → 丢 episode,I29 T-R3 bug)。
type episodeStaticTracker struct{ sent bool }

// take 返回应附带到本条 transition 的 static obs:首次调用返回 static 本身并标记
// sent,之后返回 nil。
func (t *episodeStaticTracker) take(static []int32) []int32 {
	if t.sent {
		return nil
	}
	t.sent = true
	return static
}

func (p *DMCParadigm) runEpisode(
	ctx context.Context,
	h *factory.GameHandle,
	staticInt32 []int32,
	staticHash [16]byte,
	opp oppKind,
	gpD2, gpD4 *GreedyPlayer,
	rng *rand.Rand,
	infCli gicg_actor.InferenceRequester,
	sink gicg_actor.TransitionSink,
	clientID, episodeID uint32,
	me int,
) error {
	// Per-episode seed: derive from clientID + episodeID so multi-actor / multi-episode
	// 分布唯一(seed collision = duplicate game = wasted compute)
	seed := int64(clientID)*1_000_003 + int64(episodeID)*7919
	resetSpan := gicg_actor.Span("dmc.reset_dynamic")
	h.RT.ResetDynamicWithSeeds(seed, [2]int64{seed, seed})
	resetSpan.End()
	g := h.Game
	staticSentThisEpisode := false
	// transition 侧 static:第一条被 push 的 transition 携带 static(详 episodeStaticTracker)。
	var staticTracker episodeStaticTracker

	// F1 episode-granularity batch push:在 loop 内累积 Transition slice,
	// episode done 后一次性 PushBatch。 单次 socket write 替代 N/episode 次 Push,
	// 消除 per-transition Python GIL overhead 累积(I29 F1 root cause fix)。
	// sink==nil(无 push 路径,如 headless 测试)时 txBatch 为空 + 不 push。
	var txBatch []*gicg_actor.Transition
	if sink != nil {
		txBatch = make([]*gicg_actor.Transition, 0, 16) // pre-alloc:典型 episode ~11 me-turns + 1 marker
	}

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
		var accumulateTrans bool
		// preStep* 在 actor turn 时捕获 pre-step obs/refs/pay/n_legal,Step 之后 accumulate
		// transition 用(Python DMC trainer 需 pre-step state + chosen action + post-step
		// reward 重建 DmcTransition)。 opp turn 时 nil — 不 accumulate transition for opp。
		var preStepDyn []float32
		var preStepRefs []int64
		var preStepPay []float32
		var preStepNLegal int
		if acting == me {
			if infCli == nil {
				return fmt.Errorf("inference client nil on actor turn")
			}
			reqID++
			brSpan := gicg_actor.Span("dmc.build_infer_request")
			req := BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
			brSpan.End()
			if !staticSentThisEpisode {
				req.Static = staticInt32
				staticSentThisEpisode = true
			}
			reqSpan := gicg_actor.Span("inference_client.request")
			resp, err := infCli.Request(req)
			reqSpan.End()
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
			// 捕获 pre-step state for transition accumulate(BuildInferRequest 已算了 dyn/refs/pay,
			// 复用 req fields 而非二次算 — 跟 inference 用同一份 obs guarantee 一致)。
			// refs/pay slice 到前 nlegal 段 — inference 仍走 padded(网络 forward 要 fixed
			// (max_actions, ...) shape),但 transition payload 只载 nlegal 行,buffer per-trans
			// mem ~10x 降(I29 P2 root cause:wire 含 padding × buffer_cap = 24 GB 顶峰)。
			preStepDyn = req.DynObs
			preStepRefs = req.Refs[:len(actions)*3]
			preStepPay = req.Pay[:len(actions)*DiceColorCount]
			preStepNLegal = len(actions)
			accumulateTrans = sink != nil
		} else {
			oppActions := g.GetLegalActions()
			if len(oppActions) == 0 {
				return fmt.Errorf("opp step=%d: no legal actions", step)
			}
			switch opp {
			case oppRandom:
				rndSpan := gicg_actor.Span("dmc.opp_random")
				chosen = rng.Intn(len(oppActions))
				rndSpan.End()
			case oppF1D2:
				d2Span := gicg_actor.Span("dmc.opp_f1d2_select")
				c, err := gpD2.SelectAction(h.RT)
				d2Span.End()
				if err != nil {
					return fmt.Errorf("opp f1d2 step=%d: %w", step, err)
				}
				chosen = c
			case oppF1D4:
				d4Span := gicg_actor.Span("dmc.opp_f1d4_select")
				c, err := gpD4.SelectAction(h.RT)
				d4Span.End()
				if err != nil {
					return fmt.Errorf("opp f1d4 step=%d: %w", step, err)
				}
				chosen = c
			case oppHistorical:
				// historical 对手走当前 net 推理(cost-faithful 代理;真 historical-net
				// ring 是 follow-up)。 opp 回合不 accumulate transition。
				if infCli == nil {
					return fmt.Errorf("opp historical step=%d: inference client nil", step)
				}
				reqID++
				oppReq := BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
				if !staticSentThisEpisode {
					oppReq.Static = staticInt32
					staticSentThisEpisode = true
				}
				oppResp, err := infCli.Request(oppReq)
				if err != nil {
					return fmt.Errorf("opp historical inference step=%d: %w", step, err)
				}
				if oppResp.Status != gicg_actor.InferStatusOK {
					return fmt.Errorf("opp historical inference status: %s", oppResp.ErrMsg)
				}
				chosen = pickActionEpsilonGreedy(oppResp.Logits, len(oppActions), p.cfg.Epsilon, rng)
			}
		}

		stepSpan := gicg_actor.Span("dmc.engine_step")
		g.Step(chosen)
		stepSpan.End()

		if accumulateTrans {
			// F1: accumulate transition in slice instead of per-step push。
			// 所有 in-loop transition Done=false / reward=0 —— episode 终结由 loop 后的
			// terminal marker 统一表达(详下方 marker 注释)。
			// 第一条被 accumulate 的 transition 携带 static_obs raw int32;后续 NStatic=0 由
			// Python 端 cache by static_hash 解。 用 staticTracker 而非 step==0 —— transition
			// 只在 me 回合 accumulate,对手先手时 step 0 不 accumulate(详 episodeStaticTracker)。
			staticForTrans := staticTracker.take(staticInt32)
			payload := EncodeDmcTransitionPayload(
				uint32(chosen), step, 0, preStepNLegal,
				preStepDyn, preStepRefs, preStepPay, staticForTrans, staticHash,
			)
			txBatch = append(txBatch, &gicg_actor.Transition{
				ClientID:  clientID,
				EpisodeID: episodeID,
				Step:      step,
				Done:      false,
				Payload:   payload,
			})
		}
	}

	// Episode 终结 marker:loop 退出后(GameOver 或 MaxEpisodeSteps 截断)追加一条
	// Done=true 的 terminal transition 到 txBatch,然后一次性 PushBatch。
	//
	// 必须独立于 in-loop accumulate —— transition 只在 me 回合 accumulate,对手打出致命一击
	// / 截断时最后一条 me-transition 不是终局,整个 episode 无 Done=true → Python assembler
	// 永不 finalize → _buffers 泄漏 + episode 数据丢失(I29 T-RR.1,~半数 episode 中招)。
	// marker NLegal=0:assembler 的 _capture_obs_np 对 n_legal==0 返 {} → 不产 DmcTransition,
	// marker 仅作 done 信号 + winner 载体(reward = terminalReward 从 engine g.Winner 算)。
	//
	// len(txBatch)==0(me 整局未行动 —— 对手在 me 首次行动前即结束游戏,极端情况)→
	// 不 push:assembler 端从无此 episode 的任何 transition,不会泄漏;该 episode
	// 无 me 决策、无训练价值,有意丢弃(语义保真 Python play_one_episode 的空 episode)。
	if len(txBatch) > 0 && sink != nil {
		markerPayload := EncodeDmcTransitionPayload(
			0, step, terminalReward(g, me), 0, // chosen=0, nLegal=0
			nil, nil, nil, nil, staticHash,
		)
		txBatch = append(txBatch, &gicg_actor.Transition{
			ClientID:  clientID,
			EpisodeID: episodeID,
			Step:      step,
			Done:      true,
			Payload:   markerPayload,
		})

		// Encode episode batch wire frame (含 outer length prefix + EpisodeBatchHeader + N tx records),
		// 调 sink.Push 透传 — TCP impl 走 conn.Write,SHM impl 走 ring.Push (slot bytes 含完整 frame)。
		// 失败语义:不致死 actor,本 episode 中止;actor 继续下个 episode (I29 T-RR.3 audit #5/#12)。
		encSpan := gicg_actor.Span("transition_writer.encode")
		encoded, err := gicg_actor.EncodeEpisodeBatch(clientID, episodeID, txBatch)
		encSpan.End()
		if err != nil {
			fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d ep=%d encode episode batch failed: %v\n",
				clientID, episodeID, err)
			return nil
		}
		pushSpan := gicg_actor.Span("transition_writer.push")
		err = sink.Push(clientID, episodeID, encoded)
		pushSpan.End()
		if err != nil {
			fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d ep=%d episode batch push failed "+
				"— episode aborted, actor continues: %v\n", clientID, episodeID, err)
			return nil
		}
	}
	return nil
}

// terminalReward 返回 episode 终局 me 视角的 reward。 g.Winner 取值:0/1=对应玩家胜,
// 2=engine 判定平局,-1=进行中(Go 侧 MaxEpisodeSteps 截断、engine 未达 GameOver)。
// 截断与平局同归 0 —— 语义保真 Python terminal_z(training/paradigms/dmc/_episode.py,
// winner<0 → 0.0)。
func terminalReward(g *engine.Game, me int) float32 {
	switch g.Winner {
	case me:
		return 1.0
	case 1 - me:
		return -1.0
	default: // 2=draw,-1=truncated —— 均 0
		return 0.0
	}
}
