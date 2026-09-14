package engine

// CharInfo 引擎只知道角色的结构信息，不知道 HP/能量/冻结等游戏概念。
//
// Element 是 Phase IV 后引擎认识的"角色元素色",用于 dice 系统
// (普攻 cost 引用 char 元素,tune 转换目标色)。由 interp.bind_char
// 在绑定时填入,engine 直接读取。这是"engine ignorance" 的一个刻意
// 豁免:dice 机制是核心规则而非游戏内容,元素属于核心规则。
type CharInfo struct {
	PlayerIdx int
	CharIdx   int
	Skills    []int
	Alive     bool
	Element   Element
	// SpecialtyCardRef is per-game slot occupancy; -1 means empty.
	SpecialtyCardRef int
}

// CardInst / PendingCard / PlayerState / SupportInst / MaxSupportSlots
// 见 engine/player.go。

const MaxDepth = 16

type Game struct {
	// 核心数据
	BuffDefinitions []BuffDefinition // immutable after rules load
	BuffSerial      uint64
	Buffs           []BuffInstance // live ordered instances
	Counters        []Counter
	Hooks           *HookRegistry
	RulesDigest     string // ordered, slot-bound DSL source digest; immutable after loading
	Players         [2]PlayerState

	// 游戏状态
	Phase    Phase
	Round    int
	Turn     int        // 当前行动方（0 或 1）
	FirstEnd int        // 本回合先声明结束的玩家（-1 = 尚无）
	Winner   int        // -1=进行中, 0=P0胜, 1=P1胜, 2=平局
	Failure  *RuleError // sticky execution failure; reset before reuse

	PendingAction     *Action
	PendingCardTarget *PendingCard
	PendingDice       *DiceSelection
	resume            *continuation // immutable history for an interrupted operation
	executing         *execution    // transient reconstruction cursor; never snapshotted

	// 事件栈
	eventStack []eventLayer
	depth      int // 递归保护

	// Shuffle 排列
	CounterPerm []int
	HookPerm    []int
	// CardPerm is a permutation over [0, ObsMaxCardTypes) that shuffles
	// the position a given card_ref is written to in the dynamic obs
	// hand/deck/discard buckets. Card refs are globally assigned at DSL
	// load time in a deterministic order; without shuffling, the network
	// would be able to memorize positions and skip semantic reasoning.
	// Observation uses reverseCardPerm[ref-1] as the slot index.
	CardPerm []int
	// SkillSlotPerm [2][ObsMaxChars][ObsMaxSkillsPerChar] — independent
	// permutation of [0, ObsMaxSkillsPerChar) per (player, char) slot,
	// built by InitShuffle. Used by BuildStaticObs to map the physical
	// slot index in the char-skill region to a logical index into the
	// char's SkillIDs list. Anti-position-ID-memorization (mirror of
	// the CounterPerm role for counter sids).
	SkillSlotPerm [][][]int

	// StructuralSids, if non-nil, pins counter IDs to canonical sid
	// positions 0..K-1 in InitShuffle instead of fully random. Built by
	// the interp layer (BuildStructuralCounterIDs) which knows which
	// counters are "structural" (HP/energy/alive/active/dice/
	// alive_count — things no hook body can describe) and creates
	// phantom counters (value=0, min=0, max=0) for unbound char slots
	// so the sid layout is stable across team_size configurations.
	// Remaining (mechanical) counter IDs get shuffled across sids K..n-1.
	StructuralSids []int

	// DicePaid tracks cumulative per-color dice payments by each player
	// since game start. Incremented inside PayDice. Used by IS-MCTS
	// determinization to build a Bayesian dice-color posterior:
	// Dirichlet prior (1,1,..,1) + observed paid_i → Dirichlet posterior
	// → Multinomial sample of remaining dice. Both players' payments
	// are publicly observable in real MCG rules.
	DicePaid [2][DiceColorCount]int

	// DiceTunedOut tracks cumulative per-color dice conversions OUT
	// (tune action's source_color side). Tune consumes 1 non-active
	// color and produces 1 active-element color; source is public.
	// Complements DicePaid — tune doesn't go through PayDice so wasn't
	// covered. Aggregated into sample_opponent_dice's Dirichlet α as
	// additional Bayesian evidence.
	DiceTunedOut [2][DiceColorCount]int

	// DiceTunedIn tracks cumulative per-color dice conversions IN
	// (tune action's target_color side). Currently exposed but not
	// used in posterior sampling (hard-floor modeling is Tier 3+);
	// kept for future refinement and diagnostics.
	DiceTunedIn [2][DiceColorCount]int

	// Preparing tracks per-player "skill preparing" state for the
	// prepare-skill mechanic (歼灭机关 高频旋击 → 超速旋击 等). Value
	// is the skill_id queued; 0 = no skill preparing. Set by the
	// set_preparing builtin at the end of a prepare-skill effect.
	// flipTurn() observes Preparing[newTurn]: if non-zero, that side's
	// next turn is auto-resolved (silent invoke_skill + clear) instead
	// of letting the player choose an action. See ADR-0012.
	Preparing [2]int

	// RNG. Rng is the legacy general-purpose RNG (dice rolls + DSL
	// random_non_active + obs InitShuffle). BaseSeed re-seeds it on
	// each NewRound for replay determinism (see NewRound).
	Rng      *Random
	BaseSeed int64

	// review D.5 (2026-05-14): independent per-player deck RNGs. Allows
	// "team 同 deck 不同" eval ablation (e.g. fix dice + team, vary
	// hand-draw seeds). DeckRngs[pi] used by interp/deck.go ShuffleDeck;
	// DeckSeeds[pi] survives clone/snapshot for replay. Backward compat:
	// ResetDynamicState(seed) sets DeckSeeds=[seed, seed], so legacy
	// single-seed callers see identical deck shuffles as before.
	DeckRngs  [2]*Random
	DeckSeeds [2]int64

	// Counter → 角色映射（由 DSL 层注册）
	counterCharMap map[int][2]int // counterID → [playerIdx, charIdx]

	// Name metadata (for replay/debug, not used in game logic)
	SkillNames   map[int]string    // skillID → name
	CardNames    map[int]string    // cardRef → name
	CharNames    map[[2]int]string // [playerIdx,charIdx] → name
	CounterNames map[int]string    // counterID → friendly name (e.g. "生命", "蝶火_active")

	// Canonical action hook maps, populated at DSL load time and used by
	// GameGetActionRefs to tell the pointer-net policy head which hook
	// embedding to use as each legal action's semantic representation.
	// Keyed by (ownerPlayer, ownerChar, skillID) for skills and by cardRef
	// for cards. The value is the raw hook ID (pre-HookPerm). Observation
	// code maps it to a filtered active-hook index at query time.
	CanonicalSkillHooks map[[3]int]int
	CanonicalCardHooks  map[int]int

	// Event log (nil = disabled)
	Log *EventLog

	// RewardAccum is a per-player "what happened" accumulator —
	// damage / heal / shield / reaction / kill counts. The engine
	// writes to it at the sites where the underlying event fires
	// (DealDamage, Heal, SetAlive, …); the engine itself never reads
	// RewardAccum. Python-side GreedyPlayer and diagnostic tools read
	// via GameGetRewardEvents + GameResetReward to compute per-step
	// deltas. See reward_events.go for the field layout.
	RewardAccum [2]RewardEvents

	// Obs controls which obs regions are populated and which shuffles are
	// applied. Set at construction time from GameConfig.Obs. Defaults (when
	// not set) are all-on — matching legacy behavior. Toggles exist so
	// training runs can ablate individual obs features without code changes;
	// flipping a toggle may change StaticObsSize (e.g. IncludeCharSkillRefs),
	// so ckpts trained under one toggle set aren't necessarily loadable
	// under another — the schema_version field in the Python ObsConfig
	// gates that.
	Obs ObsConfig

	// MaxRounds caps episode length. 0 = unbounded (legacy behavior).
	// When set, the game force-terminates with Winner=2 (draw) after the
	// round-end phase of the round that reaches this cap, before the next
	// round begins. The existing system/timeout.lua provides its own cap
	// at round 10 with alive-count tiebreak; MaxRounds is a lower-level
	// Go-side cap for curriculum Stage 0 where a tighter deterministic
	// ceiling (e.g. 3 rounds) is required without editing DSL.
	MaxRounds int

	// FixDice, when of length DiceColorCount, overrides Runtime.RollDice
	// to produce exactly these per-color counts every round instead of
	// random sampling. len 0 / nil = random roll (default). Used for
	// curriculum Stage 0 where dice stochasticity must be eliminated for
	// RL-pipeline validation. The caller's ``n`` argument to RollDice is
	// ignored when FixDice is active — the per-color counts express intent
	// directly (Sum(FixDice) may differ from the normal 8-dice roll).
	FixDice []int

	// Extra holds opaque interpreter / external bookkeeping. The engine
	// never reads this; it's used by interp.Runtime and friends to find
	// their per-game state from a Game pointer received inside a hook
	// callback. Set at construction time, unchanged afterwards (except
	// when cloning a Game, which updates the new Game's Extra to point
	// at the clone's Runtime).
	Extra any

	// ADR-0019 §B.3 — DSL declare_reaction("X") registry。
	// 启动期 DSL 调 declare_reaction 注册反应名 → ID;set_reaction_kind 写
	// EventContext.ReactionKind;obs encoder 用 typed ID。支持新增反应:
	// engine 0 hardcode 反应名,DSL 任何文件可 declare(包括始基反应、
	// 烈/超绽放、未来扩展)。Idempotent: 重复 declare 同名 return 同 ID。
	ReactionRegistry map[string]int // name → ID
	ReactionNames    []string       // ID → name (反查 + obs labels)

	// PendingReactionKind: DSL set_reaction_kind 在 HookReactionDamage 阶段
	// 写入此字段;damage.go 在 reaction stage hook chain 完成后 copy 到
	// ctx.ReactionKind 并 reset 为 0。每 DealDamage 入口隐含 reset(因为
	// damage.go 入口先创建 ctx 再 fire reaction hooks)。
	PendingReactionKind int

	// RecentDamageEvents — ADR-0019 §B.3 ring buffer (bounded K=8)。
	// DealDamage 出口 emit RecentDamageEvent;obs encoder 编码 ring 进 obs。
	RecentDamageEvents []RecentDamageEvent

	// damageLogStack — ADR-0019 §B.2 typed Modifier list 栈。
	// per-DealDamage call push 新 DamageModifierLog,defer pop;嵌套
	// damage call 各自独立 log,通过栈管理嵌套语义。CurrentDamageLog()
	// 取栈顶。Clone 时 stack 清空(每 game step 边界栈应为空,本字段
	// 仅在 DealDamage 调用期间非空,跨 step 不持久化)。
	damageLogStack []*DamageModifierLog
}

// ObsConfig controls per-game obs assembly + shuffle application. All
// fields default to true (legacy all-on behavior) when unset via
// NewDefaultObsConfig. Individual toggles are intended for ablations.
type ObsConfig struct {
	// IncludeCharSkillRefs: if false, BuildStaticObs still reserves the
	// char_skill_refs region (so StaticObsSize is schema-stable), but
	// fills it with -1. Training with this off + matching network arch
	// yields a clean "no skill-refs" ablation.
	IncludeCharSkillRefs bool

	// ShuffleCounters: if false, CounterPerm becomes identity (no
	// anti-ID shuffle on counter sids). Still honors StructuralSids
	// pinning when present.
	ShuffleCounters bool
	// ShuffleHooks: if false, HookPerm becomes identity.
	ShuffleHooks bool
	// ShuffleCards: if false, CardPerm becomes identity.
	ShuffleCards bool
	// ShuffleSkillSlots: if false, SkillSlotPerm becomes identity per
	// (p, c).
	ShuffleSkillSlots bool
}

// NewDefaultObsConfig returns the legacy all-on config. Used as
// fallback when GameConfig omits the obs section.
func NewDefaultObsConfig() ObsConfig {
	return ObsConfig{
		IncludeCharSkillRefs: true,
		ShuffleCounters:      true,
		ShuffleHooks:         true,
		ShuffleCards:         true,
		ShuffleSkillSlots:    true,
	}
}

func (g *Game) AddSkill(playerIdx, charIdx, skillID int) {
	ch := &g.Players[playerIdx].Chars[charIdx]
	ch.Skills = append(ch.Skills, skillID)
}

func (g *Game) GetCounterChar(counterID int) [2]int {
	if g.counterCharMap == nil {
		return [2]int{-1, -1}
	}
	if v, ok := g.counterCharMap[counterID]; ok {
		return v
	}
	return [2]int{-1, -1}
}

func (g *Game) RegisterCounterChar(counterID, playerIdx, charIdx int) {
	if g.counterCharMap == nil {
		g.counterCharMap = make(map[int][2]int)
	}
	g.counterCharMap[counterID] = [2]int{playerIdx, charIdx}
}

// --- Related code in sibling files ---
// game_clone.go   — DeepCopy / RestoreFrom / ResetDynamicState / Snapshot
// game_counter.go — counter CRUD + write pipeline + event stack
// game_shuffle.go — InitShuffle + state accessors
