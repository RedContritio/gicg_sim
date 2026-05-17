package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	"encoding/json"
	"gicg_mono/gicg_engine/record"
	"os"
)

// Replay / view-export C exports. Labels, counter/hook labels, card
// names, dynamic obs, forced-switch pending, FreeString, and main() live
// in capi_labels.go.

// Returns the engine's textual replay record (Chinese-language YAML) for
// the current game, identical in format to what record.Export emits for
// Go integration tests. Caller must free with GameFreeString.
//
//export GameExportReplay
func GameExportReplay(id C.int) *C.char {
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	if h.RT == nil {
		return C.CString("# no runtime\n")
	}
	return C.CString(record.Export(h.RT))
}

// Returns the live game state as a JSON-encoded record.StateView. This
// is the structured, typed-field view intended for rendering (web UI,
// diagnostic tools) — distinct from GameExportReplay which emits the
// past-tense textual replay. Caller must free with GameFreeString.
// See gicg_engine/record/export_view.go for the StateView schema.
//
//export GameExportViewJSON
func GameExportViewJSON(id C.int) *C.char {
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	if h.RT == nil {
		return C.CString("{}")
	}
	view := record.ExportView(h.RT)
	blob, err := json.Marshal(view)
	if err != nil {
		return C.CString("{\"error\":\"marshal failed\"}")
	}
	return C.CString(string(blob))
}

// Rewinds the game held by `id` to the point immediately after the first
// `step` actions of the record at `yamlPath` have been executed. Assumes
// the handle's team roster and card pool already match the record (use
// RecordExtractInfoJSON from Python to build a compatible env first).
// Returns a JSON blob: {"view": StateView, "step": N, "total_steps": M,
// "rounds": R, "winner": -1/0/1}. On error returns {"error": "..."}.
// Caller must free with GameFreeString.
//
//export GameReplayToJSON
func GameReplayToJSON(id C.int, yamlPath *C.char, step C.int) *C.char {
	h := getHandle(int(id))
	if h == nil {
		return C.CString(`{"error":"invalid handle"}`)
	}
	if h.RT == nil {
		return C.CString(`{"error":"no runtime"}`)
	}
	data, err := os.ReadFile(C.GoString(yamlPath))
	if err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "read yaml: " + err.Error()})
		return C.CString(string(blob))
	}
	rec, err := record.Parse(string(data))
	if err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "parse: " + err.Error()})
		return C.CString(string(blob))
	}
	if err := record.ReplayTo(h.RT, rec, int(step)); err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "replay: " + err.Error()})
		return C.CString(string(blob))
	}
	view := record.ExportView(h.RT)
	wrapper := map[string]interface{}{
		"view":        view,
		"step":        int(step),
		"total_steps": record.TotalSteps(rec),
		"rounds":      len(rec.Rounds),
		"winner":      rec.Winner,
	}
	blob, err := json.Marshal(wrapper)
	if err != nil {
		return C.CString(`{"error":"marshal failed"}`)
	}
	return C.CString(string(blob))
}

// Parses the YAML record at `yamlPath` and returns metadata needed to
// construct a compatible GicgEnv for replaying it — teams, total step
// count, number of rounds, winner. Handle-free: does not require a
// running game. Used by the web replay API to build an env on demand.
// Returns JSON: {"teams": [[...p0...], [...p1...]], "total_steps": N,
// "rounds": M, "winner": -1/0/1}. On error: {"error": "..."}.
// Caller must free with GameFreeString.
//
//export RecordExtractInfoJSON
func RecordExtractInfoJSON(yamlPath *C.char) *C.char {
	data, err := os.ReadFile(C.GoString(yamlPath))
	if err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "read yaml: " + err.Error()})
		return C.CString(string(blob))
	}
	rec, err := record.Parse(string(data))
	if err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "parse: " + err.Error()})
		return C.CString(string(blob))
	}
	teams, err := record.ExtractTeams(rec)
	if err != nil {
		blob, _ := json.Marshal(map[string]string{"error": "extract teams: " + err.Error()})
		return C.CString(string(blob))
	}
	wrapper := map[string]interface{}{
		"teams":       [2][]string{teams[0], teams[1]},
		"total_steps": record.TotalSteps(rec),
		"rounds":      len(rec.Rounds),
		"winner":      rec.Winner,
	}
	blob, err := json.Marshal(wrapper)
	if err != nil {
		return C.CString(`{"error":"marshal failed"}`)
	}
	return C.CString(string(blob))
}
