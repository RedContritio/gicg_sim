package enginev2

// A20 — Substate state first-class declared (private mutation kind, A1 一致)。
// A26 — Multi-instance substate: declare_substate 是 template,enter_substate 时
//       **实例化新 state container set** (每实例独立 declared);多 instance 并存时
//       各自隔离 + 自动 GC on exit (recycle pool 含 dirty detection)。
//
// 全 typed: SubstateInitData / SubstateExitData 是 union struct,
// SubstateAction 是 typed enum + 字段 (取代旧 map[string]any payload)。
//
// prototype 验证场景: 千织 3-of-4 召唤物挑选 (临时 collection 持 candidates)。

// SubstateActionKind — substate 内部 RL 可选的 sub-action 类型。
// 跟 game-level SubActionKind 是两回事 (前者是 substate-private, 后者是 SubAction pipeline)。
type SubstateActionKind int

const (
	SubstateActionExit    SubstateActionKind = iota // 退出 substate
	SubstateActionSelect                            // 选 candidate idx
	SubstateActionConfirm                           // 确认选择 (例: 千织挑完 3 个 confirm)
)

// SubstateAction — substate 内部一次 RL 选择的 typed payload。
type SubstateAction struct {
	Kind        SubstateActionKind
	SelectedIdx int // SubstateActionSelect / Confirm 用
}

// SubstateInitData — enter_substate 时的 typed init 数据 (union struct)。
// 每 substate template 自己知道用哪个字段;不允许 map[string]any。
type SubstateInitData struct {
	// 通用挑选: 候选 items 列表 (典型: 千织 4 个候选召唤物)
	Candidates []Item

	// 烈絮特技 sub-skill set (skill_set collection 初始化)
	SkillSet []*SkillRef

	// CostPayment substate 的支付规格
	CostSpec *CostSpec
}

// SubstateExitData — ExitSubstate 时的 typed result (union struct)。
type SubstateExitData struct {
	SelectedIndices []int       // 通用挑选结果 (千织 picked indices)
	ChosenSkillIdx  int         // 烈絮选了哪个 sub-skill
	PaidDice        []DiceColor // CostPayment 实际支付骰子序列
	PickedItems     []Item      // collection 里挑出的 items (例: 千织 picked summons)
}

// SubstateTemplate — declare_substate 注册的 schema。
type SubstateTemplate struct {
	Name         string
	StateSchema  []SubstateField                                     // 实例化时按 schema 创建 declared scalar/collection
	LegalActions func(inst *SubstateInstance) []SubstateAction       // RL agent step 看到的 legal actions
	OnAction     func(inst *SubstateInstance, action SubstateAction) // agent 选 action 后 engine 调
}

type SubstateFieldKind int

const (
	FieldScalar SubstateFieldKind = iota
	FieldCollection
)

type SubstateField struct {
	Name           string
	Kind           SubstateFieldKind
	InitInt        int    // scalar
	MinInt, MaxInt int    // scalar bounds
	MaxItems       int    // collection
	ItemOwnership  string // collection: "instance" | "shared"
}

// SubstateInstance — 一次 enter_substate 后 engine 实例化的 state container set。
// 每实例独立持有 scalar/collection (跟 game-level container 隔离)。
type SubstateInstance struct {
	TemplateName string
	InstanceID   int // 0..N,recycle pool 用
	Scalars      map[string]*Scalar
	Collections  map[string]*Collection
	InitData     *SubstateInitData // typed init 数据
	Exited       bool
	ExitResult   *SubstateExitData // typed exit 数据
}

// SubstateRegistry — engine-level 注册表 + recycle pool。
type SubstateRegistry struct {
	Templates map[string]*SubstateTemplate
	pools     map[string][]*SubstateInstance // free instances per template name
	nextID    int
}

func NewSubstateRegistry() *SubstateRegistry {
	return &SubstateRegistry{
		Templates: map[string]*SubstateTemplate{},
		pools:     map[string][]*SubstateInstance{},
	}
}

func (r *SubstateRegistry) DeclareSubstate(t *SubstateTemplate) {
	if _, exists := r.Templates[t.Name]; exists {
		panic("substate template duplicate: " + t.Name)
	}
	r.Templates[t.Name] = t
}

// EnterSubstate — 实例化新 state container set (或从 pool recycle)。
// recycle 时强制 reset (dirty detection: 还原到 schema InitInt + clear collection)。
func (r *SubstateRegistry) EnterSubstate(name string, initData *SubstateInitData) *SubstateInstance {
	tpl, ok := r.Templates[name]
	if !ok {
		panic("substate template not declared: " + name)
	}
	var inst *SubstateInstance
	if pool := r.pools[name]; len(pool) > 0 {
		inst = pool[len(pool)-1]
		r.pools[name] = pool[:len(pool)-1]
		// dirty detect: reset scalar 到 schema InitInt (不是 zero) + clear collection
		schemaInit := map[string]int{}
		for _, f := range tpl.StateSchema {
			if f.Kind == FieldScalar {
				schemaInit[f.Name] = f.InitInt
			}
		}
		for fname, s := range inst.Scalars {
			s.Value = schemaInit[fname]
			s.clamp()
		}
		for _, c := range inst.Collections {
			c.Items = c.Items[:0]
		}
		inst.Exited = false
		inst.ExitResult = nil
	} else {
		inst = &SubstateInstance{
			TemplateName: name,
			InstanceID:   r.nextID,
			Scalars:      map[string]*Scalar{},
			Collections:  map[string]*Collection{},
		}
		r.nextID++
		// 按 schema 实例化 state container
		for _, f := range tpl.StateSchema {
			if f.Kind == FieldScalar {
				inst.Scalars[f.Name] = &Scalar{
					Name:  name + "/" + f.Name + "@" + intToStr(inst.InstanceID),
					Value: f.InitInt, Min: f.MinInt, Max: f.MaxInt,
				}
			} else {
				inst.Collections[f.Name] = &Collection{
					Name:          name + "/" + f.Name + "@" + intToStr(inst.InstanceID),
					MaxSize:       f.MaxItems,
					ItemOwnership: f.ItemOwnership,
				}
			}
		}
	}
	inst.InitData = initData
	// init_data 按 typed 字段 populate (template 自己知道用哪个)
	if initData != nil {
		// 通用挑选: 把 Candidates 灌入名为 "candidates" 的 collection (template 约定)
		if len(initData.Candidates) > 0 {
			if c, ok := inst.Collections["candidates"]; ok {
				c.Items = append(c.Items[:0], initData.Candidates...)
			}
		}
		// 烈絮: 把 SkillSet 灌入名为 "skill_set" 的 collection
		if len(initData.SkillSet) > 0 {
			if c, ok := inst.Collections["skill_set"]; ok {
				c.Items = c.Items[:0]
				for _, sk := range initData.SkillSet {
					c.Items = append(c.Items, sk)
				}
			}
		}
	}
	return inst
}

// ExitSubstate — 标 exited + 写 ExitResult,instance 入 pool recycle。
func (r *SubstateRegistry) ExitSubstate(inst *SubstateInstance, result *SubstateExitData) {
	inst.Exited = true
	inst.ExitResult = result
	r.pools[inst.TemplateName] = append(r.pools[inst.TemplateName], inst)
}

// PoolStats — debug 用,暴露 free pool 大小
func (r *SubstateRegistry) PoolStats() map[string]int {
	out := map[string]int{}
	for k, v := range r.pools {
		out[k] = len(v)
	}
	return out
}

func intToStr(n int) string {
	if n == 0 {
		return "0"
	}
	digits := ""
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		digits = string(rune('0'+n%10)) + digits
		n /= 10
	}
	if neg {
		digits = "-" + digits
	}
	return digits
}
