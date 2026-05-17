package main

/*
#include <stdlib.h>
*/
import "C"

// Snapshot / restore / free + log suspend / resume exports.
//
// These five were present in capi.go before the 24-file split refactor
// (3c194e8) but were dropped from the refactor's output by mistake,
// leaving the Python-side ctypes bindings pointing at nonexistent
// symbols. Restored here — the Python test harness (every GicgEnv
// construction runs _setup_api) needs them.
//
// Snapshot/restore is the state handle for MCTS rollouts and for
// GreedyPlayer depth>=2 speculative stepping; suspend/resume mutes the
// event log during MCTS forward sim so inner rollouts don't pollute
// the real game's replay.

//export GameSnapshot
func GameSnapshot(id C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	snap := h.Game.DeepCopy()
	snapMu.Lock()
	defer snapMu.Unlock()
	sid := nextSnapID
	nextSnapID++
	snapshots[sid] = snap
	return C.int(sid)
}

//export GameRestore
func GameRestore(id C.int, snapID C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	snapMu.Lock()
	snap := snapshots[int(snapID)]
	snapMu.Unlock()
	if snap == nil {
		return -1
	}
	h.Game.RestoreFrom(snap)
	return 0
}

//export GameSnapshotFree
func GameSnapshotFree(snapID C.int) {
	snapMu.Lock()
	defer snapMu.Unlock()
	delete(snapshots, int(snapID))
}

// GameLogSuspend detaches the event log from the live game so that
// Log.Append guards (`if g.Log != nil`) skip all writes until
// GameLogResume. Use case: MCTS forward-simulation — inner rollouts
// don't belong in the real game's replay, and the write overhead
// (log append + string formatting in counter_write events + growing
// slice allocations) accumulates with every simulated step. Returns
// 0 on success, -1 on invalid handle, -2 if the log was already
// suspended.
//
//export GameLogSuspend
func GameLogSuspend(id C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	if h.SuspendedLog != nil {
		return -2
	}
	h.SuspendedLog = h.Game.Log
	h.Game.Log = nil
	return 0
}

// GameLogResume re-attaches the event log suspended by
// GameLogSuspend. Any events that would have been appended while
// suspended are permanently lost — that's the point. Returns 0 on
// success, -1 on invalid handle, -2 if no suspended log is held.
//
//export GameLogResume
func GameLogResume(id C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	if h.SuspendedLog == nil {
		return -2
	}
	h.Game.Log = h.SuspendedLog
	h.SuspendedLog = nil
	return 0
}
