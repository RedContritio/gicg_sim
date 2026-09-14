package strictjson

import (
	"reflect"
	"testing"
)

func TestDecodeRejectsLossyInputsAtomically(t *testing.T) {
	type sample struct {
		Count  int
		Flag   bool
		Slots  [2]int
		Values map[string]int
	}
	valid := `{"Count":4,"Flag":true,"Slots":[1,2],"Values":{"x":3}}`
	var got sample
	if err := Decode([]byte(valid), &got); err != nil {
		t.Fatal(err)
	}
	before := got
	for _, src := range []string{
		`{"Count":4,"Flag":true,"Slots":[1],"Values":{"x":3}}`,
		`{"Count":4,"Flag":true,"Slots":[1,2,3],"Values":{"x":3}}`,
		`{"Count":4,"Flag":true,"Slots":[1,null],"Values":{"x":3}}`,
		`{"Count":4,"Flag":null,"Slots":[1,2],"Values":{"x":3}}`,
		`{"Count":4,"Flag":true,"Slots":[1,2],"Values":{"x":null}}`,
		`{"Flag":true,"Slots":[1,2],"Values":{"x":3}}`,
		`{"Count":4,"Count":5,"Flag":true,"Slots":[1,2],"Values":{"x":3}}`,
		`{"Count":4,"count":5,"Flag":true,"Slots":[1,2],"Values":{"x":3}}`,
		`{"Count":4,"Flag":true,"Slots":[1,2],"Values":{"x":3,"x":4}}`,
		valid + ` {}`, "null",
	} {
		if err := Decode([]byte(src), &got); err == nil {
			t.Errorf("accepted lossy input %s", src)
		}
		if !reflect.DeepEqual(got, before) {
			t.Fatal("failed decode changed destination")
		}
	}
}
