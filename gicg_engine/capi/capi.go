package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	"encoding/json"
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
	"gicg_mono/gicg_engine/interp"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// Handle table — capi exposes opaque int IDs to Python; GameHandle and
// game construction live in gicg_engine/factory so the Go-native actor
// pool (gicg_actor/) can share the same factory entry point.

var (
	handleMu sync.Mutex
	handles  = map[int]*factory.GameHandle{}
	nextID   = 1

	snapMu     sync.Mutex
	snapshots  = map[int]*engine.Game{}
	nextSnapID = 1
)

func storeHandle(h *factory.GameHandle) int {
	handleMu.Lock()
	defer handleMu.Unlock()
	id := nextID
	nextID++
	handles[id] = h
	return id
}

func getHandle(id int) *factory.GameHandle {
	handleMu.Lock()
	defer handleMu.Unlock()
	return handles[id]
}

func removeHandle(id int) {
	handleMu.Lock()
	defer handleMu.Unlock()
	delete(handles, id)
}

// Eagerly read + parse every *.lua file under the given data
// directory and populate the interp package's DSL cache. Call this
// once at training launch so mid-run DSL edits don't cause workers
// that haven't yet called GameNew to observe a partially-written
// file. Returns 0 on success, -1 on error (e.g. dataDir not a
// directory, parse error in some .lua file). Errors print to
// stderr.
//
// Safe to call multiple times — cache entries are already-parsed
// no-ops on re-preload.
//
//export DSLPreload
func DSLPreload(dataDir *C.char) C.int {
	root := C.GoString(dataDir)
	var paths []string
	err := filepath.Walk(root, func(p string, info os.FileInfo, e error) error {
		if e != nil {
			return e
		}
		if info.IsDir() {
			return nil
		}
		if strings.HasSuffix(p, ".lua") {
			paths = append(paths, p)
		}
		return nil
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "DSLPreload walk error: %v\n", err)
		return -1
	}
	if err := interp.PreloadDSLFiles(paths); err != nil {
		fmt.Fprintf(os.Stderr, "DSLPreload parse error: %v\n", err)
		return -1
	}
	return 0
}

//export GameNew
func GameNew(configJSON *C.char) C.int {
	var cfg factory.GameConfig
	if err := json.Unmarshal([]byte(C.GoString(configJSON)), &cfg); err != nil {
		return -1
	}
	h, err := factory.NewGame(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "GameNew error: %v\n", err)
		return -1
	}
	return C.int(storeHandle(h))
}

//export GameFree
func GameFree(id C.int) {
	removeHandle(int(id))
}

//export GameClone
func GameClone(id C.int) C.int {
	src := getHandle(int(id))
	if src == nil {
		return -1
	}
	cloneRT := src.RT.Clone()
	return C.int(storeHandle(&factory.GameHandle{Game: cloneRT.Game, RT: cloneRT}))
}

// C exports split across sibling files:
//   capi_snap.go    — snapshot / restore / snapshot_free / log suspend-resume
//   capi_actions.go — action loop, legal actions, setters, step
//   capi_state.go   — state / counters / obs size + bytes
//   capi_reward.go  — RewardEvents accumulator getter / reset
//   capi_labels.go  — labels / replay / utility / main()
