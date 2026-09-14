package main

/*
#include <stdlib.h>
#include <string.h>

// mcts_send_cb pushes an eval request to Python without waiting for
// the response. Returns 0 on success, non-zero to abort.
typedef int (*mcts_send_cb)(
    int worker_id, int game_id,
    const int* dyn_obs, int dyn_len,
    const int* refs, const int* pay, int n_legal);

// mcts_recv_cb blocks for the next eval response and writes it into
// caller-provided buffers. n_legal tells it how many prior slots to
// expect. Returns 0 on success, non-zero to abort.
typedef int (*mcts_recv_cb)(
    int n_legal,
    float* out_prior, float* out_value);

static int call_mcts_send(mcts_send_cb cb,
    int worker_id, int game_id,
    const int* dyn_obs, int dyn_len,
    const int* refs, const int* pay, int n_legal) {
    return cb(worker_id, game_id, dyn_obs, dyn_len, refs, pay, n_legal);
}

static int call_mcts_recv(mcts_recv_cb cb,
    int n_legal, float* out_prior, float* out_value) {
    return cb(n_legal, out_prior, out_value);
}
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"unsafe"

	mcts "gicg_mono/gicg_mcts"
)

// MCTSSearchJSONInput mirrors the JSON payload Python sends for one
// search call. Config, root info (prior + actions + value), and the
// pre-sampled determinizations are bundled into one JSON string so
// we need exactly one cgo crossing for all non-buffer args.
//
// RootActions is a flat [][13]int32 where each row is [kind, sub_a,
// sub_b, sub_c, sub_d, pay0..pay7] — matches ActionId layout.
type MCTSSearchJSONInput struct {
	Config           mcts.Config   `json:"config"`
	RootPrior        []float32     `json:"root_prior"`
	RootValue        float32       `json:"root_value"`
	RootActions      [][]int32     `json:"root_actions"`
	Determinizations []MCTSDetJSON `json:"determinizations"`
	WorkerID         int32         `json:"worker_id"`
	GameID           int32         `json:"game_id"`
	Seed             uint64        `json:"seed"`
}

// MCTSDetJSON is the serialized form of mcts.Determinization.
type MCTSDetJSON struct {
	Opponent int32   `json:"opponent"`
	Hand     []int32 `json:"hand"`
	Deck     []int32 `json:"deck"`
	Dice     []int32 `json:"dice"`
}

// Runs a full MCTS search. Callback contract:
//
//	sendCB(worker, game, dyn, refs, pay, n_legal) — non-blocking
//	  push onto the eval pipe.
//	recvCB(n_legal, out_prior, out_value) — block for next response
//	  and fill out_prior (len n_legal) + out_value.
//
// Search drives both on a single goroutine, so responses arrive in
// send order (FIFO) and no correlation ID is needed.
//
// Returns 0 on success; negative on error.
//
//export MCTSSearch
func MCTSSearch(
	handleID C.int,
	snapID C.int,
	inputJSON *C.char,
	sendCB C.mcts_send_cb,
	recvCB C.mcts_recv_cb,
	visitsOut *C.int,
	visitsCap C.int,
	rootValueOut *C.float,
	profileJSONOut **C.char,
) C.int {
	h := getHandle(int(handleID))
	if h == nil {
		return -1
	}
	snapMu.Lock()
	snap := snapshots[int(snapID)]
	snapMu.Unlock()
	if snap == nil {
		return -2
	}

	var in MCTSSearchJSONInput
	if err := json.Unmarshal([]byte(C.GoString(inputJSON)), &in); err != nil {
		return -3
	}

	rootActions := make([]mcts.ActionId, len(in.RootActions))
	for i, ra := range in.RootActions {
		if len(ra) != 13 {
			return -4
		}
		rootActions[i] = mcts.ActionId{
			Kind: ra[0], SubA: ra[1], SubB: ra[2], SubC: ra[3], SubD: ra[4],
		}
		for c := 0; c < 8; c++ {
			rootActions[i].Payment[c] = ra[5+c]
		}
	}

	dets := make([]mcts.Determinization, len(in.Determinizations))
	for i, d := range in.Determinizations {
		dets[i] = mcts.Determinization{
			Opponent: d.Opponent,
			Hand:     d.Hand,
			Deck:     d.Deck,
			Dice:     d.Dice,
		}
	}

	sendFn := func(req *mcts.EvalRequest) error {
		var dynPtr, refsPtr, payPtr *C.int
		if len(req.DynObs) > 0 {
			dynPtr = (*C.int)(unsafe.Pointer(&req.DynObs[0]))
		}
		if req.NLegal > 0 {
			refsPtr = (*C.int)(unsafe.Pointer(&req.Refs[0]))
			payPtr = (*C.int)(unsafe.Pointer(&req.Pay[0]))
		}
		rc := C.call_mcts_send(
			sendCB,
			C.int(req.WorkerID), C.int(req.GameID),
			dynPtr, C.int(len(req.DynObs)),
			refsPtr, payPtr, C.int(req.NLegal),
		)
		if rc != 0 {
			return fmt.Errorf("send callback returned %d", int(rc))
		}
		return nil
	}

	recvFn := func(resp *mcts.EvalResponse) error {
		var priorPtr *C.float
		if len(resp.Prior) > 0 {
			priorPtr = (*C.float)(unsafe.Pointer(&resp.Prior[0]))
		}
		valuePtr := (*C.float)(unsafe.Pointer(&resp.Value))
		rc := C.call_mcts_recv(
			recvCB,
			C.int(len(resp.Prior)),
			priorPtr, valuePtr,
		)
		if rc != 0 {
			return fmt.Errorf("recv callback returned %d", int(rc))
		}
		return nil
	}

	searchInput := &mcts.SearchInput{
		Runtime:          h.RT,
		Snap:             snap,
		Config:           &in.Config,
		RootPrior:        in.RootPrior,
		RootValue:        in.RootValue,
		RootActions:      rootActions,
		Determinizations: dets,
		SendEval:         sendFn,
		RecvEval:         recvFn,
		WorkerID:         in.WorkerID,
		GameID:           in.GameID,
		Seed:             in.Seed,
	}

	result, err := mcts.Search(searchInput)
	if err != nil {
		return -5
	}

	n := len(result.Visits)
	if n > int(visitsCap) {
		return -6
	}
	if n > 0 {
		arr := unsafe.Slice((*C.int)(unsafe.Pointer(visitsOut)), n)
		for i, v := range result.Visits {
			arr[i] = C.int(v)
		}
	}

	*rootValueOut = C.float(result.RootValue)

	if result.Profile != nil && profileJSONOut != nil {
		prof := map[string]any{
			"n_rollouts":       result.Profile.NRollouts.Load(),
			"n_restore":        result.Profile.NRestore.Load(),
			"n_determinize":    result.Profile.NDeterminize.Load(),
			"n_eval":           result.Profile.NEval.Load(),
			"n_rollout":        result.Profile.NRollout.Load(),
			"n_descend":        result.Profile.NDescend.Load(),
			"n_commit":         result.Profile.NCommit.Load(),
			"n_env_query":      result.Profile.NEnvQuery.Load(),
			"n_env_step":       result.Profile.NEnvStep.Load(),
			"n_rollout_steps":  result.Profile.NRolloutSteps.Load(),
			"n_d1_trigger":     result.Profile.ND1Trigger.Load(),
			"n_d1_new_actions": result.Profile.ND1NewActions.Load(),
			"restore_s":        float64(result.Profile.RestoreNS.Load()) / 1e9,
			"determinize_s":    float64(result.Profile.DeterminizeNS.Load()) / 1e9,
			"eval_s":           float64(result.Profile.EvalNS.Load()) / 1e9,
			"rollout_s":        float64(result.Profile.RolloutNS.Load()) / 1e9,
			"descend_s":        float64(result.Profile.DescendNS.Load()) / 1e9,
			"commit_s":         float64(result.Profile.CommitNS.Load()) / 1e9,
			"env_query_s":      float64(result.Profile.EnvQueryNS.Load()) / 1e9,
			"env_step_s":       float64(result.Profile.EnvStepNS.Load()) / 1e9,
			"total_s":          float64(result.Profile.TotalNS.Load()) / 1e9,
			// Preflight for state-level eval cache. Upper-bound
			// hit rate = 1 - unique/total.
			"unique_eval_keys": result.Profile.UniqueEvalKeys.Load(),
		}
		b, _ := json.Marshal(prof)
		*profileJSONOut = C.CString(string(b))
	}

	return 0
}
