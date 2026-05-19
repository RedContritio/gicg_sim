# IR Compiler Test Specification — Hook-DSL → 3-Address-Code

**Scope**: defines semantic-level test cases for the GICG hook-DSL → IR compiler. Each case is implementation-agnostic: an implementer can encode them in any Go (or other) test format. Inputs are Lua source + typed-binding context; outputs are IR ops, structural assertions, or error patterns.

**Conventions used in this doc**:
- `r0, r1, ...` denote ascending register IDs (the compiler's exact numbering is allowed to vary; tests should assert *relative* structure unless an absolute number is meaningful, e.g. for arg-block contiguity).
- `NullReg` denotes the implementation's sentinel "no register" value.
- "Op sequence" assertions enumerate ops in order; "structural" assertions count or pattern-match without fixing exact order beyond what's stated.
- "Bindings: ∅" = no closure-captured idents.
- Token names (`TokDealDamage`, `TokKwSource`, `TokMHp`, …) are referenced symbolically; their integer values come from the engine tokenizer and are stable per IR-2.

---

## 1. Coverage Matrix

Each row is (AST node, variant) → test ID(s) covering it. Section 2 has the full spec per ID. Any cell with no test ID = coverage gap.

| AST node | Variants → Test IDs |
|---|---|
| LocalDecl | single+RHS=T-001; no-RHS=T-002; nil-RHS=T-003; multi-name=T-004; binding-creating (get_counter / declare_counter / declare_card / get_char / get_skill) = T-005..T-009 |
| Assign | ctx.field=T-010; in-scope reassign=T-011; undeclared→err=T-012; outer-chunk→err=T-013; closure-captured→err=T-014; non-ctx dot-assign→err=T-015 |
| IfStmt | single-arm=T-020; if-else=T-021; if-elseif=T-022; if-elseif-else=T-023; nested=T-024; empty arm=T-025; early-return idiom=T-026 |
| ReturnStmt | bare mid-block=T-030; last-stmt=T-031; in arm=T-032 (subsumed); with-value→err=T-033 |
| ExprStmt | call=T-040; method=T-041; bare ident→err=T-042 |
| NumberLit | positive=T-050; zero=T-051; negative=T-052; max=T-053; min=T-054; oob-high→err=T-055; oob-low→err=T-056; float→err=T-057 |
| BoolLit / NilLit / StringLit | true=T-060; false=T-061; nil=T-062 (distinct opcode); string→err=T-063 |
| Ident | local=T-070; closure Counter/Card/Char/Skill=T-071..T-074; undefined→err=T-075 |
| BinOp | arith=T-080; eq/neq=T-081; ordering=T-082; logical=T-083; operand-order=T-084; nested=T-085; in if-cond=T-086 |
| UnaryOp | NOT=T-090; NEG (distinct from literal)=T-091 |
| DotAccess | ctx.field=T-100; Enum.Value=T-101; char-attr field-style=T-102; non-binding dot→err=T-103 |
| IndexAccess | `_chars[i]`=T-110; `_char_by_slot[p][c]`=T-111; partial 2D→err=T-112; other→err=T-113 |
| MethodCall (counter) | `:get` ×4 scopes=T-120..T-123; `:set` ×4=T-124..T-127; `:get_at` 1-arg=T-128, 2-arg=T-129; `:set_at` 2-arg=T-130, 3-arg=T-131; `:add` 1-arg=T-132, 0-arg=T-133; `:sub` PerPlayer=T-134, ActiveStatus=T-135; `:add_at` 2-arg=T-136, 3-arg=T-137; `:sub_at`=T-138; `:cmin`=T-139; `:cmax`=T-140; `:decay_all` 1-arg=T-141; `:fill_all` 2-arg=T-142 |
| MethodCall (char-attr) | all 8 methods ×0-arg=T-150..T-157; with arg→err=T-158 |
| MethodCall errors | unknown counter method=T-159; counter method on Card=T-160; char-attr on Counter=T-161; non-ident receiver=T-162 |
| Call | positional builtin=T-170; +TableCtor kwargs=T-171; multi-key kwargs=T-172; defer_fn=T-173; defer_fn arity err=T-174 (OQ-7); 0-arg=T-175; unknown ident→err=T-176; non-ident func→err=T-177 |
| TableCtor | in Call last-arg=T-171/T-180; multi-key=T-172/T-181; empty=T-182; outside Call→err=T-183; nested→err=T-184; numeric-key→err=T-185 |
| FuncLit | defer_fn last-arg=T-173; non-last-arg→err=T-190; LocalDecl RHS→err=T-191; ExprStmt→err=T-192; nested defer_fn=T-193 |

---

## 2. Test Cases (Semantic Specs)

Notation:
- `Bindings: { name → kind/id }` — closure-captured names with typed binding kind and opaque id.
- For brevity, `ctr(N)` = `{ TypedBinding kind=Counter, id=N }`, `card(N)` = Card, `ch(N)` = Char, `sk(N)` = Skill.

### Unit goldens — literals & loads

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-001 | `local x = 5` | ∅ | `OpLoadImm r0 5`; bind `x→r0`. |
| T-002 | `local x` | ∅ | `OpLoadNil r0`; bind `x→r0`. (Implementer may instead bind with NullReg; document choice. Default: OpLoadNil.) |
| T-003 | `local x = nil` | ∅ | `OpLoadNil r0`. Crucially NOT `OpLoadImm r0 0`. |
| T-004 | `local a, b = 1, 2` | ∅ | `OpLoadImm r0 1; OpLoadImm r1 2`; bind `a→r0, b→r1`. |
| T-005 | `local c = get_counter("foo", Scope.PerPlayer)` | ∅ | Result-reg registered as Counter binding for `c`; subsequent `c:get()` compiles to `OpLoadAddr AddrCounter`. (Whether an OpCall to TokGetCounter appears is implementer choice — IR-2 may strip.) |
| T-006 | `local c = declare_counter("foo", Scope.PerPlayer, 0, {min=0,max=1})` | ∅ | Same as T-005; verify chaining `c:add(1)` → `OpCall Op1=TokMAdd Op2=<counter_id> Op3=arg_base`. |
| T-007 | `local ref = declare_card("x", { dices = { any = 1 } })` | ∅ | Bind `ref → Card`; `if ctx.card_ref ~= ref then return end` compiles. |
| T-008 | `local 天星 = get_char("天星")` | ∅ | Bind `天星 → Char`; `天星:hp()` compiles to char-attr OpLoadAddr. |
| T-009 | `local s = get_skill(天星, "枪")` | `天星 → ch(7)` | Bind `s → Skill`. |

### Unit goldens — Assign / scope

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-010 | `ctx.playable = false` | ∅ | `OpLoadImm r0 0; OpStoreAddr Dst=r0 Op1=AddrCtxField Op2=TokCtxPlayable Op3=NullReg`. |
| T-011 | `local x = 0\nx = 1` | ∅ | `OpLoadImm r0 0; OpLoadImm r1 1`. Binding `x` updated to r1 (reg-reuse is OK if final value of `x` reads as 1). |
| T-012 | `y = 1` | ∅ | Error matches `/implicit global not allowed/`. |
| T-013 | `if true then x = 1 end` (where `x` declared in enclosing outer chunk) | n/a | Error matches `/reassignment to outer-scope/`. |
| T-014 | `c = 0` | `c → ctr(0)` | Error matches `/cannot assign to closure-captured/`. |
| T-015 | `foo.bar = 1` (foo not ctx) | ∅ | Error contains `ctx` (e.g. `/assignment.*non-ctx/`). |

### Unit goldens — IfStmt control flow

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-020 | `if x > 0 then deal_damage(Target.EnemyActive, Element.Physical, 1) end` | `x → ctr(0)` | 1 OpCJump; Op1=GT-result reg; Op2 = op-index immediately after the deal_damage OpCall. |
| T-021 | `if c then deal_damage(...,1) else deal_damage(...,2) end` | `c → ctr(0)` | Exactly 1 OpCJump (skip-then) + 1 OpJump (skip-else). Then- and else-bodies each contain 1 OpCall TokDealDamage. |
| T-022 | `if a then ... elseif b then ... end` (no else) | `a,b → ctr` | 2 OpCJumps + 1 OpJump (between arms). |
| T-023 | `if a then ... elseif b then ... else ... end` | `a,b → ctr` | 2 OpCJumps + 2 OpJumps. Last arm has no trailing jump. |
| T-024 | `if a then if b then deal_damage(...,1) end end` | `a,b → ctr` | 2 OpCJumps properly nested: inner CJump.Op2 within outer's body span. |
| T-025 | `if a then end` | `a → ctr(0)` | 1 OpCJump, target = next op after it. Must not produce malformed IR. |
| T-026 | `if ctx.card_ref ~= ref then return end` | `ref → card(0)` | OpCJump body contains an OpReturn; OpCJump.Op2 points past the OpReturn. |

### Unit goldens — Return / ExprStmt

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-030 | `if x then return end\ndeal_damage(...,1)` | `x → ctr(0)` | OpReturn precedes the deal_damage OpCall in stream order. |
| T-031 | `deal_damage(...,1)\nreturn` | ∅ | OpCall then OpReturn (then the compiler's appended terminal OpReturn — so possibly 2 OpReturns; see C-012). |
| T-032 | (Covered by T-026 / T-030.) | | |
| T-033 | `return 1` | ∅ | Error matches `/return.*value/` or `/unsupported return/`. Hook bodies are void. |
| T-040 | `deal_damage(Target.EnemyActive, Element.Physical, 1)` | ∅ | 3 arg loads (2× AddrEnum + 1× Imm); arg-gather to contiguous block; `OpCall Dst=NullReg Op1=TokDealDamage Op2=3 Op3=reg_base`. |
| T-041 | `c:add(1)` | `c → ctr(0)` | `OpLoadImm r0 1; OpCall Dst=NullReg Op1=TokMAdd Op2=0 Op3=r0`. |
| T-042 | `x` (bare ident) | `x → ctr(0)` | Error matches `/expression statement.*not.*call/` or `/unsupported expr-stmt/`. |

### Unit goldens — NumberLit / BoolLit / NilLit / StringLit

| ID | Lua | Expected |
|---|---|---|
| T-050 | `local x = 7` | `OpLoadImm r0 7`. |
| T-051 | `local x = 0` | `OpLoadImm r0 0` (NOT OpLoadNil). |
| T-052 | `local x = -1` | r0 holds -1. Sign-folded literal OR Imm+UnaryNeg both accepted; golden asserts final value. |
| T-053 | `local x = 32767` | `OpLoadImm r0 32767`. |
| T-054 | `local x = -32768` | r0 holds -32768. Recommend sign-fold in parser → direct `OpLoadImm r0 -32768`. |
| T-055 | `local x = 32768` | Error matches `/out of int16 range/`. |
| T-056 | `local x = -32769` | Error matches `/out of int16 range/`. |
| T-057 | `local x = 1.5` | Error contains `integer` or `int16` substring. |
| T-060 | `local x = true` | `OpLoadImm r0 1`. |
| T-061 | `local x = false` | `OpLoadImm r0 0`. |
| T-062 | `local x = nil` | `OpLoadNil r0`. Cross-check: opcode integer == 13, NOT 1. |
| T-063 | `local x = "foo"` | Error contains `string`. |

### Unit goldens — Ident

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-070 | `local x = 5\nlocal y = x` | ∅ | `OpLoadImm r0 5; OpLoadReg r1 r0`. |
| T-071 | `local v = c:get()` | `c → ctr(7)` | `OpLoadAddr r0 AddrCounter 7 NullReg`; bind `v→r0`. |
| T-072 | `if ctx.card_ref == ref then end` | `ref → card(3)` | At `ref` use-site: `OpLoadAddr rX AddrLocalVar <id-of-ref> NullReg`. |
| T-073 | `local h = 天星:hp()` | `天星 → ch(2)` | Receiver loaded via `OpLoadAddr AddrLocalVar <id>`, then `OpLoadAddr AddrCharAttr TokMHp <receiver_reg>`. |
| T-074 | `if ctx.skill_index ~= s then return end` | `s → sk(5)` | `OpLoadAddr AddrLocalVar <id-of-s>` present; NEQ compare against ctx.skill_index reg. |
| T-075 | `local x = y` | ∅ | Error matches `/undefined identifier|implicit global/`. |

### Unit goldens — BinOp / UnaryOp

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-080 | `local x = 2+3` (parametrize for SUB/MUL/DIV) | ∅ | `OpLoadImm r0 2; OpLoadImm r1 3; OpBinOp r2 ADD r0 r1`. Same shape per arith kind. |
| T-081 | `if ctx.value == 1 then end` / `~= 1` | ∅ | `OpBinOp Op1=EQ` / `Op1=NEQ`. |
| T-082 | `if x < 0 then end` (parametrize LT/GT/LE/GE) | `x → ctr(0)` | Matching BinOpKind. |
| T-083 | `if a and b then end` / `or` | `a,b → ctr` | `OpBinOp Op1=AND` / `OR`. Non-short-circuit (see OQ-1). |
| T-084 | `local x = a-b; local y = b-a` | `a → ctr(0), b → ctr(1)` | In `x`: Op2=reg(a), Op3=reg(b). In `y`: Op2=reg(b), Op3=reg(a). Compiler MUST NOT swap. |
| T-085 | `local x = (a+b)*c` | `a,b,c → ctr` | 3 OpBinOps; inner `+` result feeds outer `*` as lhs. |
| T-086 | `if x > 0 then deal_damage(...,1) end` | `x → ctr(0)` | `OpBinOp GT → cond_reg`; OpCJump cond_reg → past-then. |
| T-090 | `if not (c:get() > 0) then return end` | `c → ctr(0)` | Contains `OpUnaryOp Op1=NOT`. |
| T-091 | `local x = -y` | `y → ctr(0)` | `OpLoadAddr ... → r0; OpUnaryOp r1 NEG r0`. NOT folded into LoadImm. |

### Unit goldens — Dot/Index

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-100 | `local v = ctx.value` | ∅ | `OpLoadAddr r0 AddrCtxField TokCtxValue NullReg`. |
| T-101 | `local e = Element.Fire` | ∅ | `OpLoadAddr r0 AddrEnum TokElementFire NullReg`. |
| T-102 | `tracked_elem:set_at(p, c.element)` | `tracked_elem → ctr(0), p, c local` | `c.element` compiles to `OpLoadAddr AddrCharAttr Op2=TokMElement Op3=<c_reg>` (field-style = 0-arg method alias, OQ-3). |
| T-103 | `local v = foo.bar` (foo unbound) | ∅ | Error matches `/undefined|implicit global/`. |
| T-110 | `local c = _chars[ctx.actor_player]` | ∅ | `OpLoadAddr r0 AddrCtxField TokCtxActorPlayer; OpCall r1 TokBridgeChars n_pos=1 Op3=r0`. |
| T-111 | `local ch = _char_by_slot[p][c1]` | `p → ctr(0)`, c1 local | `OpCall TokBridgeCharBySlot n_pos=2 Op3=rB` with the 2 preceding arg regs holding p,c1 contiguously at rB,rB+1. |
| T-112 | `local row = _char_by_slot[p]` | `p → ctr(0)` | Error matches `/unsupported IndexAccess/`. |
| T-113 | `local v = some_table[1]` | ∅ | Error matches `/unsupported IndexAccess/`. |

### Unit goldens — MethodCall (counter, all-scope)

Shared shape: `Bindings: { c → ctr(N) }`. Scope is binding metadata, not visible in IR — the compiler must emit the *same* IR for the same syntactic form across scopes. Differences are runtime arity validation.

| ID | Lua | Expected |
|---|---|---|
| T-120..T-123 | `local v = c:get()` (one test per scope: PerPlayer/PerChar/ActiveStatus/Self) | `OpLoadAddr r0 AddrCounter N NullReg`. IR identical across scopes. |
| T-124..T-127 | `c:set(7)` (4 scopes) | `OpLoadImm r0 7; OpStoreAddr Dst=r0 AddrCounter N NullReg`. |
| T-128 | `local v = c:get_at(ctx.actor_player)` (1-arg, PerPlayer) | `OpLoadAddr rIdx AddrCtxField TokCtxActorPlayer; OpLoadAddr rOut AddrCounter N rIdx`. |
| T-129 | `local v = c:get_at(p, ch)` (2-arg, PerChar) | Per OQ-2: load p,ch into contiguous rB, rB+1; `OpLoadAddr rOut AddrCounter N rB`. Op3 = base of index-arg span; runtime decodes by scope. |
| T-130 | `c:set_at(p, 5)` (2-arg, PerPlayer) | Load p→rP, 5→rV; `OpStoreAddr Dst=rV AddrCounter N rP`. |
| T-131 | `c:set_at(p, ch, 0)` (3-arg, PerChar) | Per OQ-2: load p,ch,0 contig rB..rB+2; `OpStoreAddr Dst=rB+2 AddrCounter N rB`. |
| T-132 | `c:add(1)` (PerPlayer) | `OpLoadImm r0 1; OpCall Dst=NullReg TokMAdd N r0`. |
| T-133 | `c:add()` (Self, 0-arg) | `OpCall Dst=NullReg TokMAdd N NullReg`. **Compiler MUST NOT reject 0-arg.** |
| T-134 | `c:sub(1)` (PerPlayer) | As T-132 with TokMSub. |
| T-135 | `c:sub()` (ActiveStatus) | As T-133 with TokMSub. |
| T-136 | `c:add_at(p, 1)` (2-arg, PerPlayer) | Args contig rB,rB+1; `OpCall TokMAddAt N rB`. |
| T-137 | `c:add_at(p, ch, 1)` (3-arg, PerChar) | Args contig rB..rB+2; `OpCall TokMAddAt N rB`. |
| T-138 | `c:sub_at(p, 1)` | As T-136 with TokMSubAt. |
| T-139 | `local lo = c:cmin()` (PerChar) | `OpCall Dst=r0 TokMCMin N NullReg`. Dst non-null (returns value). |
| T-140 | `if hp:get() < hp:cmax() then ... end` (`hp → ctr(K)`) | Contains `OpCall Dst=<reg> TokMCMax K NullReg`. |
| T-141 | `c:decay_all(1)` (PerChar) | `OpLoadImm r0 1; OpCall Dst=NullReg TokMDecayAll N r0`. **Critical: 1-arg form must compile.** |
| T-142 | `c:fill_all(1, 5)` (PerChar) | Args contig rB,rB+1; `OpCall Dst=NullReg TokMFillAll N rB`. **Critical: 2-arg form must compile.** |

### Unit goldens — MethodCall (char-attr)

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-150..T-157 | `local v = ch:hp()` (parametrize: hp, energy, alive, owner_player, owner_char, name, element, weapon) | `ch → ch(0)` | `OpLoadAddr r0 AddrLocalVar <id-of-ch> NullReg; OpLoadAddr r1 AddrCharAttr Tok<Method> r0`. Per-method test fixes Op2 token. |
| T-158 | `ch:hp(1)` | `ch → ch(0)` | Error matches `/char-attr.*0[ -]arg|hp.*arity/`. |

### Unit goldens — MethodCall errors

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-159 | `c:foo()` | `c → ctr(0)` | Error matches `/unknown method|method.*foo/`. |
| T-160 | `ref:get()` | `ref → card(0)` | Error matches `/method.*on.*Card|invalid receiver/`. |
| T-161 | `c:hp()` | `c → ctr(0)` | Error matches `/method.*on.*Counter|invalid receiver/`. |
| T-162 | `(a + b):get()` | `a,b → ctr` | Error matches `/method.*non-ident|unsupported receiver/`. |

### Unit goldens — Call (builtin / defer_fn)

| ID | Lua | Bindings | Expected |
|---|---|---|---|
| T-170 | `deal_damage(Target.EnemyActive, Element.Physical, 1)` | ∅ | 3 arg loads (2 AddrEnum + 1 Imm); arg-gather (may be elided if regs already contiguous); exactly 1 `OpCall Dst=NullReg TokDealDamage Op2=3 Op3=reg_base`. Structural: regs reg_base..reg_base+2 hold the 3 arg values. |
| T-171 | `deal_damage(Target.EnemyActive, Element.Physical, 1, { source = Source.Skill })` | ∅ | Compile kwarg value → rK; emit `OpKwArg TokKwSource rK`; gather positional contig rB..rB+2; `OpCall Dst=NullReg TokDealDamage Op2=3 Op3=rB`. Structural: exactly 1 OpKwArg(TokKwSource) immediately precedes the OpCall (gather OpLoadRegs may interleave; no other OpCall between them). |
| T-172 | `deal_damage(..., { source = Source.Summon, element = Element.Fire })` | ∅ | 2 OpKwArgs (TokKwSource, TokKwElement, in TableCtor field order) preceding the OpCall. |
| T-173 | `defer_fn(function() deal_damage(Target.EnemyAll, Element.Ice, 1, { source = Source.Reaction }) end)` | ∅ | Main: exactly 1 `OpDeferFn Op1=<lambda_idx>`, 0 `OpCall TokDeferFn` (OpCall is replaced). CompiledHook.Lambdas length ≥ 1; Lambdas[lambda_idx] contains OpCall TokDealDamage preceded by OpKwArg TokKwSource. |
| T-174 | `defer_fn(extra, function() ... end)` | ∅ | Per OQ-7 default: error matches `/defer_fn.*arity/`. If engine signature allows leading positional args, adjust expectation. |
| T-175 | `local p = context_player()` | ∅ | `OpCall Dst=r0 TokContextPlayer Op2=0 Op3=NullReg`. |
| T-176 | `foo()` (foo undefined) | ∅ | Error matches `/unknown builtin|undefined.*foo/`. |
| T-177 | `(a + b)(x)` | `a,b,x → ctr` | Error matches `/non-ident.*function|unsupported call/`. |

### Unit goldens — TableCtor / FuncLit

| ID | Lua | Expected |
|---|---|---|
| T-180/T-181 | (covered by T-171/T-172.) | |
| T-182 | `deal_damage(Target.EnemyActive, Element.Physical, 1, {})` | 0 OpKwArgs preceding the OpCall. No spurious OpKwArg. |
| T-183 | `local t = {}` | Error matches `/TableCtor.*not in.*call|unsupported table/`. |
| T-184 | `deal_damage(..., { a = { b = 1 } })` | Error matches `/nested.*table|unsupported.*table.*value/`. |
| T-185 | `deal_damage(..., { [1] = 1 })` | Error matches `/numeric.*key|string.*key.*required/`. |
| T-190 | `defer_fn(function() end, 1)` | Error matches `/FuncLit.*last-arg|defer_fn.*signature/`. |
| T-191 | `local f = function() end` | Error matches `/FuncLit.*only supported in defer_fn/`. |
| T-192 | `function() end` (standalone) | Parser- or compile-level error matches `/FuncLit.*expression statement|standalone/`. |
| T-193 | `defer_fn(function() defer_fn(function() heal(Target.OwnActive, 1) end) end)` | Main: 1 OpDeferFn → lambda L1. Lambdas[L1]: 1 OpDeferFn → lambda L2. Lambdas[L2]: OpCall heal. CompiledHook.Lambdas length ≥ 2. |

---

## 3. Contract / Invariant Tests

| ID | Intent | Test shape |
|---|---|---|
| C-001 | `methodMap` (counter/char-attr tokens) ∩ `tokenMap` (builtin tokens) = ∅. Otherwise OpCall.Op1 dual semantics ambiguous. | Build both token-ID sets; assert intersection empty. |
| C-002 | Every name in `counterMethods` resolves via `LookupMethod` to a non-zero token (else compile silently emits `OpCall Op1=0`). | Parametrize over the 12 method names; assert each lookup ≠ 0. |
| C-003 | Same as C-002 for `charAttrMethods` (8 names). | Parametrize. |
| C-004 | `counterMethods` set equals exactly `{get, set, get_at, set_at, add, sub, add_at, sub_at, cmin, cmax, decay_all, fill_all}` — no zombies, no missing. | String-set equality. |
| C-005 | `charAttrMethods` set equals exactly `{hp, energy, alive, owner_player, owner_char, name, element, weapon}`. | String-set equality. |
| C-006 | Every kwarg key (TokKwSource, TokKwElement, TokKwTarget, TokKwValue, TokKwMin, TokKwMax, TokKwTag, TokKwDices, TokKwAny, TokKwMatch, TokKwBattleAction, TokKwRequiresChar, …) resolves via `LookupKwArg` to a non-zero token. | Parametrize. |
| C-007 | `TokBridgeChars` / `TokBridgeCharBySlot` resolve to non-zero AND are disjoint from C-001 sets. | Assert non-zero + disjoint. |
| C-008 | Reg-cap error message contains the integer "32" (= MaxRegs) and the word "register". Prevents silent constant drift. | Synthesize a hook allocating >32 regs; match error substring. |
| C-009 | Opcodes are exactly the 14 distinct integers `{0..13}`. Adding a new opcode must not collide. | Build set from constants; assert size 14 and equals {0..13}. |
| C-010 | AddrKind values are exactly: AddrCtxField=1, AddrCounter=2, AddrCharAttr=3, AddrLocalVar=4, AddrEnum=5. | Exact integer asserts. |
| C-011 | BinOpKind {1..12} distinct; UnaryOpKind {1..2} distinct; AddrKind range disjoint from both. | Set asserts. |
| C-012 | Every successful compile has `MainOps[last] == OpReturn` (compiler appends a terminal OpReturn). | Sweep over a fixture set of compiling Lua bodies; assert tail op. |
| C-013 | defer_fn lambda body can read parent closure bindings. With parent `c → ctr(0)`, inner `c:add(1)` compiles to `OpCall TokMAdd Op2=0` inside the lambda's IR. | Setup from T-193; assert structural. |

---

## 4. Integration Tests (real DSL files)

Each integration test loads the .lua source, builds binding context from top-level `declare_*`/`get_*` calls (test fixture may extract once per file), compiles every hook body, and asserts: no errors, every hook's MainOps non-empty, MainOps[last]==OpReturn. Additional structural assertions per the table.

### 4.1 test_basic pool

| ID | Path | Bindings | Structural assertions |
|---|---|---|---|
| I-001 | `data/pools/test_basic/cards/测试卡_增幅.lua` | `ref→Card, buff→Counter(PerPlayer)` | 2 hooks compile. `on_card_play`: ≥1 OpCJump (early-return) + ≥1 OpStoreAddr AddrCounter (set_at). `on_damage_mul`: 2 OpCJumps (early-return guards) + ≥1 OpStoreAddr AddrCtxField (`ctx.value = ctx.value*2`). |
| I-002 | `data/pools/test_basic/cards/测试卡_碎片.lua` | `ref→Card` | 1 hook; contains OpCall TokDealDamage with Op2=3 and 0 OpKwArgs. |
| I-003 | `data/pools/test_basic/cards/测试卡_神秘水流.lua` | `ref→Card, used_skill→Counter(PerPlayer)` | 3 hooks compile. `on_card_play`: 1 OpCJump (card_ref guard) + 1 BinOp GT (`:get_at(...) > 0`) + 2 OpCall TokDealDamage (one per arm). |

### 4.2 v_legacy pool (sampled)

| ID | Path | Notable usage | Assertions |
|---|---|---|---|
| I-010 | `v_legacy/cards/L1/碌碌无为.lua` | baseline | All hooks compile. |
| I-011 | `v_legacy/cards/L2/占星.lua` | `_chars[i]` | ≥1 OpCall TokBridgeChars. |
| I-012 | `v_legacy/cards/L2/诅咒.lua` | `_chars[i]` | ≥1 OpCall TokBridgeChars. |
| I-013 | `v_legacy/cards/L3/以牙还牙.lua` | `_char_by_slot`, `c.element` field-style, `:set_at(p,v)` PerPlayer, `:set(2)`, `:get_at(Player.Enemy)`, `:sub(1)`, deal_damage with TableCtor | 5 hooks compile. ≥1 hook with OpCall TokBridgeCharBySlot Op2=2. `on_switch`: contains OpLoadAddr AddrCharAttr TokMElement. `on_round_end_post_summon`: OpKwArg TokKwSource precedes OpCall TokDealDamage. |
| I-014 | `v_legacy/cards/L3/速速茶点.lua` | `_chars[i]` | ≥1 OpCall TokBridgeChars. |
| I-015 | `v_legacy/cards/L4/玄冰.lua` | `defer_fn`, `ctx.element` assign | `on_reaction_damage` MainOps has OpDeferFn. Lambdas length ≥1; Lambdas[0] has OpCall TokDealDamage preceded by OpKwArg TokKwSource. Main has OpStoreAddr AddrCtxField TokCtxElement. |
| I-016 | `v_legacy/cards/L4/铁弓.lua` | `_chars[i]` | ≥1 OpCall TokBridgeChars. |
| I-017 | `v_legacy/cards/L5/星愿.lua` | many (`_char_by_slot`, `ch.hp` field-style, `:cmax`, multi-counter) | 9 hooks compile. ≥1 OpCall (or OpLoadAddr per OQ-4) carrying TokMCMax. ≥2 `on_after_write` hooks contain OpCall TokBridgeCharBySlot. |
| I-018 | `v_legacy/cards/L6/以逸待劳.lua` | `defer_fn` | ≥1 hook with OpDeferFn + non-empty Lambdas. |
| I-019 | `v_legacy/characters/赤蝶/赤蝶_蝶火.lua` | char buff with `get_skill` | All hooks compile; if deal_damage with TableCtor present, OpKwArg precedes OpCall. |

### 4.3 Aggregate sweep

**I-100** — iterate every `.lua` under `data/pools/test_basic/` and `data/pools/v_legacy/`. Per file: extract bindings from top-level decls, compile every hook. Assert no errors. Failure message must include file path + hook name + error.

Soft assertion: total counter LoadAddr/StoreAddr op count across sweep ≥ 100 (audit observed ~178 `:get/:set/:get_at/:set_at` calls; slack for partial pools).

---

## 5. Expected-Failure Documentation

The compiler rejects the following DSL patterns with the listed error substrings. Each entry: example source, expected error substring, design rationale.

| # | Example | Error substring | Why |
|---|---|---|---|
| F-01 | `local x = "foo"` | `string` | StringLit reserved for token names; runtime has no string runtime, IR is integer-tagged. |
| F-02 | `local v = someTable[1]` | `unsupported IndexAccess` | Only `_chars[i]` and `_char_by_slot[p][c]` patterns are bridge-recognized. |
| F-03 | `local f = function() end` | `FuncLit only supported in defer_fn` | Hook bodies are static; lambdas only exist for deferred-execution semantics. |
| F-04 | `defer_fn(function() end, 1)` | `FuncLit.*last-arg` | FuncLit must be the trailing argument. |
| F-05 | `foo.bar = 1` (foo not ctx) | `assignment.*non-ctx` (or `undefined`) | Only ctx-field stores are supported via OpStoreAddr AddrCtxField. |
| F-06 | `(a+b):get()` | `method.*non-ident` | Method receiver must be a single identifier binding. |
| F-07 | `local t = {}` | `TableCtor.*not in.*call` | TableCtor is only meaningful as a Call argument (it desugars to OpKwArg stream). |
| F-08 | (outer-chunk reassign — see T-013 setup) | `reassignment to outer-scope` | Prevents accidental shared-state across blocks; inner shadow with `local` is allowed. |
| F-09 | `y = 1` (no decl) | `implicit global not allowed` | Globals reserved for bridge tables only. |
| F-10 | `c = 0` (c closure-captured) | `cannot assign to closure-captured` | Closure bindings are read-only references; mutation goes through counter methods. |
| F-11 | `local x = 32768` | `out of int16 range` | All Op operands are int16-packed; literal range is `[-32768, 32767]`. |
| F-12 | `local x = 1.5` | `integer` | NumberLit must be integer; floats unsupported. |
| F-13 | `return 1` | `return.*value` | Hook bodies are void. |
| F-14 | `c:foo()` | `unknown method` | Counter method set is closed (12 names). |
| F-15 | `c:hp()` (c=counter binding) | `invalid receiver` | Char-attr methods require Char binding receiver. |
| F-16 | `ch:hp(1)` | `char-attr.*0[ -]arg` | Char-attr methods are 0-arg projections. |
| F-17 | `deal_damage(..., { [1]=x })` | `numeric.*key` | TableCtor must use string keys (kwargs). |
| F-18 | `deal_damage(..., { a={b=1} })` | `nested.*table` | TableCtor values must be simple expressions, not nested tables. |
| F-19 | `foo()` (foo undefined builtin) | `unknown builtin` | Call func must be a known builtin ident. |
| F-20 | `x` (bare ident as ExprStmt) | `expression statement` | ExprStmt must be a call. |
| F-21 | Hook with > MaxRegs distinct regs | `register` and `32` | Reg cap is constant; rewrite hook to reuse regs or split. |
| F-22 | `_char_by_slot[p]` (1-D partial) | `unsupported IndexAccess` | The bridge is 2-D only. |

---

## 6. Test Organization Recommendation

Suggested logical groupings (file/suite count is implementer's call):

1. **Unit goldens — primitives & literals**: T-001..T-091 (LocalDecl/Assign/IfStmt/Return/ExprStmt/literals/Ident/BinOp/UnaryOp). Each fixture = Lua + bindings + expected op sequence or structural property.
2. **Unit goldens — Dot/Index**: T-100..T-113.
3. **Unit goldens — method calls**: T-120..T-162. Parametrize over (method, scope) for counters; (method) for char-attrs. Errors grouped at end.
4. **Unit goldens — Call/TableCtor/FuncLit**: T-170..T-193. Kwarg-ordering most fragile; encode expected ordering in test names.
5. **Contracts/invariants**: C-001..C-013. Standalone (no Lua fixtures); compiler-internals introspection.
6. **Integration**: I-001..I-100. Sweep (I-100) is regression backstop; individual I-NNN cases pin specific features so sweep failure still yields precise signal.
7. **Expected-failure registry**: F-01..F-22. Parametrized over (source, expected_substring); single source of truth for rejection contract.

Naming: prefix unit goldens by AST category for grep-ability (e.g. `numberlit_max_int16`, `methodcall_counter_set_at_perchar`). Integration tests embed file basename (e.g. `integration_yiyahuanya_compiles`).

---

## 7. Open Questions / Ambiguities (chosen interpretation noted)

| ID | Topic | Chosen interpretation |
|---|---|---|
| OQ-1 | Short-circuit for `and`/`or` | IR-3 is strict (non-short-circuit). DSL BinOps observed in audit are pure (no side effects). Document in compiler header; revisit if side-effecting BinOps added. |
| OQ-2 | `:get_at`/`:set_at` Op3 encoding for 2-arg index | Op3 = base reg of contiguous index-arg block; count implied by scope (runtime-known). Compiler emits OpLoadReg ops to gather index args contiguously before LoadAddr/StoreAddr. |
| OQ-3 | Char-attr field-style vs method-style (`c.element` vs `c:element()`) | Both desugar to the same `OpLoadAddr AddrCharAttr`. Field-style is sugar; compiler recognizes char-attr names in DotAccess on Char-binding receivers. |
| OQ-4 | Chained handle (`hp:cmax()` where `hp = 天星:hp()`) | Compiler's binding inference treats `:hp()` return as Counter-bound, so `:cmax()` chained call routes through counter-method path. I-017 pins assertion conservatively (accepts either OpCall TokMCMax or OpLoadAddr AddrCharAttr TokMCMax). |
| OQ-5 | OpReturn placement | Compiler unconditionally appends terminal OpReturn; explicit `return` mid-block emits additional OpReturn. Two OpReturns allowed. C-012 asserts tail. |
| OQ-6 | `local x` (no RHS) | Emit `OpLoadNil Dst=r0`, bind `x→r0`. Unifies with `local x = nil` (T-002 / T-003). |
| OQ-7 | `defer_fn` arity | Default: 1-arg (FuncLit only). T-174 expects error. If engine signature differs, adjust T-174. |

---

## 8. Done Criteria (for the test suite implementing this spec)

- All cells in Section 1's coverage matrix have at least one referenced test.
- All Section 2 test cases either pass or are explicitly skipped with a written reason linking back to an open question.
- All Section 3 invariants pass.
- All Section 4 integration tests pass on a clean checkout against the listed .lua files.
- All Section 5 expected-failure patterns produce an error containing the documented substring.
- A coverage report (line/branch on the compiler module) reaches ≥ 90% on compiler logic; uncovered branches must be linked to an open question or explicitly listed as "intentionally unreachable defensive guard, to be removed".
