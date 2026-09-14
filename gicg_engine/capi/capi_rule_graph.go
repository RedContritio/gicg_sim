package main

/*
#include <stdlib.h>
*/
import "C"

import "encoding/json"

//export GameGetRuleGraphJSON
func GameGetRuleGraphJSON(id C.int) *C.char {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	blob, err := json.Marshal(h.Game.BuildObservationRuleGraph())
	if err != nil {
		panic(err)
	}
	return C.CString(string(blob))
}
