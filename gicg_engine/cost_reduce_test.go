package engine

import "testing"

func TestDiceCostReduceRestrictedFirst(t *testing.T) {
	for _, tc := range []struct {
		name   string
		before DiceCost
		amount int
		want   DiceCost
	}{
		{"mixed", DiceCost{Specific: [7]int{2}, Match: 2, Any: 4}, 3, DiceCost{Match: 1, Any: 4}},
		{"normal", DiceCost{Specific: [7]int{1}, Any: 2}, 3, DiceCost{}},
		{"elemental", DiceCost{Specific: [7]int{3}}, 3, DiceCost{}},
		{"same", DiceCost{Match: 2}, 3, DiceCost{}},
		{"any", DiceCost{Any: 4}, 3, DiceCost{Any: 1}},
		{"negative slots", DiceCost{Specific: [7]int{-1}, Match: 2, Any: 4}, 3, DiceCost{Specific: [7]int{-1}, Any: 3}},
		{"zero", DiceCost{Any: 4}, 0, DiceCost{Any: 4}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := tc.before
			got.Reduce(tc.amount)
			if got != tc.want {
				t.Fatalf("got %+v want %+v", got, tc.want)
			}
		})
	}
}
