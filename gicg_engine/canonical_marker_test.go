package engine

import (
	"reflect"
	"testing"
)

func TestCanonicalMarkerExposesKindNotIdentity(t *testing.T) {
	a, b, c := make([]int32, 15), make([]int32, 15), make([]int32, 15)
	CanonicalHookRepr{Marker: 1, Kind: 1}.WriteObsInts(a)
	CanonicalHookRepr{Marker: 137, Kind: 1}.WriteObsInts(b)
	CanonicalHookRepr{Marker: 1, Kind: 2}.WriteObsInts(c)
	if !reflect.DeepEqual(a, b) {
		t.Fatal("internal ID leaked into canonical observation")
	}
	if reflect.DeepEqual(a, c) || a[0] != 15 {
		t.Fatal("definition kind missing or aliased with literal opcode")
	}
}
