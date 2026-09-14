---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: eval-protocol
subtopic: service
---

# Eval Service — socket daemon + paradigm-agnostic poll daemon

> 本 subtopic 锚定 GICG eval service 协议 — `tools/eval/eval_service.py`
> socket daemon(production,AZ / CFR 用)+ `tools/eval/daemon.py`
> paradigm-agnostic poll daemon(DMC Phase 3.5 起新方向)。两者并
> 存于 P1-P2 阶段,本 spec 同时治理,接口分歧由 transitional note 标
> 出。
>
> 源 truth:`tools/eval/eval_service.py` + `tools/eval/eval_service_server.py`
> + `tools/eval/eval_service_job.py` + `tools/eval/eval_service_schema.json` +
> `tools/eval/daemon.py` + `tools/eval/_paradigm.py`。

## 1. Scope

本 subtopic 覆盖:

- Legacy socket daemon(`tools/eval/eval_service.py`):socket bind / JSON
  request / DSL cache warm / dispatch / heartbeat / shutdown
- JSON Schema 2020-12 验证(`eval_service_schema.json`):4 kinds
  (gauntlet / status / stop / schema)、player_spec oneOf、
  scenario cfg 字段
- ServiceState mutable counters + metrics.jsonl logging
- `tools/eval/daemon.py` poll-based daemon:rsync + ckpt mtime 监听 +
  paradigm adapter dispatch + eval_metrics.jsonl + TensorBoard
- Paradigm adapter registry(`tools/eval/_paradigm.py`):
  `load_config` / `build_agent` / `build_evaluator` / `build_baseline`
  / `ckpt_frame` keys

不覆盖:

- Gauntlet matchup 算法 / cell 内 game loop — [`./gauntlet.md`](./gauntlet.md)
- Baseline player 实施 — [`./baselines.md`](./baselines.md)
- AZ arena ckpt 替换决定 — [`./arena.md`](./arena.md)

## 2. Legacy socket daemon — `tools/eval/eval_service.py`

### 2.1 Process layout

```
Long-running daemon process (one global singleton):
  - Bind Unix socket: ${GICG_EVAL_SOCKET:-/tmp/gicg_eval.sock}
  - Warm DSL cache: preload_dsl(--data-dir)  [default: data]
  - ThreadPoolExecutor(--workers default 2)
  - Accept loop: timeout 1s, recv 64 KB JSON, dispatch
  - Status heartbeat every 60s → log_metric('heartbeat', ...)
```

Training runs / `tools/send_matchup` 客户端 connect-send-recv-close
per request(no persistent connection)。

### 2.2 SHALL invariants

1. Service SHALL be **global singleton** — 单 socket path 同时只一
   个 service instance。多 run 共享同一 service(节省 DSL cache 与
   ckpt load 成本)。详 `memory project_eval_service_global`。

2. Socket path SHALL be configurable via `GICG_EVAL_SOCKET` env var
   (容器部署用 named volume `/var/run/gicg/eval.sock`)+ `--socket`
   CLI flag。

3. Service SHALL `preload_dsl(data_dir)` at startup **before** accepting
   connections — gauntlet job SHALL be immune to mid-run DSL edits。

4. Stale socket file SHALL be `unlink`ed at startup(`start()` 内实
   施)— 防 previous crash 残留 file 阻塞 bind。

5. SIGINT / SIGTERM SHALL be caught + clean shutdown(`server.stop()`
   + `socket.unlink()`)。

6. Accept loop SHALL `settimeout(1.0)` 周期 check `_stop_event`,SHALL
   NOT block forever on `accept`。

## 3. JSON request schema

### 3.1 Schema authority

- File:`tools/eval/eval_service_schema.json`
- Dialect:JSON Schema 2020-12(`Draft202012Validator`)
- `$id`:`gicg/eval_service/v1`
- 验证器:`jsonschema.Draft202012Validator` 在 `make_validator`
  构造 + fail-fast check_schema

### 3.2 SHALL invariants

1. Service SHALL validate every incoming request against the schema
   via `validate_request(req, validator)`。Schema errors SHALL return
   `{"status": "error", "message": "schema: <path>: <message>"}`,
   service SHALL NOT 静默接受。

2. Runtime-only invariants(JSON Schema 不能表达)SHALL be 单独 check
   — 当前唯一:az/cfr ckpt 文件存在性。Future runtime checks SHALL
   加入 `validate_request` 而非散在 dispatch。

3. Schema is **single source of truth** — `tools/send_matchup` CLI
   arg parser SHALL 从 schema 生成 help text(避免文档与实施漂移)。

4. New request kind SHALL be added by extending top-level `oneOf`;
   new player type SHALL extend `$defs.player_spec.oneOf`(详
   schema description)。

### 3.3 4 kinds(2026-05-15 shipped)

- `gauntlet` — 一次 matchup,append result JSONL
- `status` — return active / completed / errors / queued / uptime
- `stop` — graceful shutdown
- `schema` — return schema itself(client introspection)

### 3.4 Player specs(oneOf)

- `player_spec_az_or_cfr`:type ∈ {az, cfr},required `ckpt`,
  optional `n_simulations`(0 = argmax)
- `player_spec_random`:type = random
- `player_spec_mcts_pure`:type = mcts_pure,required `n_simulations`
  ≥ 1
- `player_spec_greedy`:type = greedy,`features` ∈ {F1..F5}(default
  F1),`depth` ∈ {1, 2, 3}(default 1),optional `dice_greedy` bool

详 [`./baselines.md`](./baselines.md)。

### 3.5 Gauntlet request 主字段

- `kind: "gauntlet"`(required)
- `players: [PlayerSpec, PlayerSpec]`(required,2 items)
- `mode: "fixed" | "enumerate_disjoint"`(required)
- `team_0` / `team_1` — required iff `mode=fixed`
- `char_pool` + `team_size` — required iff `mode=enumerate_disjoint`
- `card_pool` / `deck_padding` / `pool` — ADR-0011 scenario cfg
- `deck_0` / `deck_1` — F4 explicit per-player decks(card-name
  multiset;requires `mode=fixed`;null = 隐式 eligible-set 路径)
- `games_per_cell: int ≥ 1`(default 10)
- `max_game_steps: int ≥ 1`(default 400)
- `swap_sides: bool`(default true)
- `result_path: str`(required,JSONL append target)
- `seed: int`(default 0)/ `game_marker: int`(default 0)
- `id: str`(optional,server 自动 `g<marker:05d>` if absent)
- `data_dir: str | null`(default null,DSL 已 warmed 在 service 端)

## 4. Job dispatch + ServiceState

### 4.1 SHALL invariants

1. `EvalServer._handle_connection` SHALL dispatch kind via:
   - `status` → return counters JSON(non-blocking)
   - `stop` → return `{"status": "stopping"}` + set `_stop_event`
   - `schema` → return parsed schema JSON
   - `gauntlet` → validate, assign `id`, increment `accepted`,
     submit to ThreadPoolExecutor, return `{"status": "accepted",
     "id": <id>}`

2. `run_gauntlet_job(req, state)` SHALL:
   - increment `state.active` at start, decrement at end (finally
     block 保证)
   - Invoke `run_matchup(...)` from `training.framework.matchup.matchup`
   - Append JSONL entry `{id, game_marker, **result.to_dict()}` to
     `req['result_path']`(parent mkdir(parents=True, exist_ok=True))
   - Log metric `job_done` or `job_fail` to service metrics JSONL
   - Print `[eval] done ...` / `[eval] FAIL ...` with wall_s
   - Warn if `wall_s > 1800s`(`_SLOW_JOB_WARN_S`)

3. `ServiceState` 整数 counter(`active` / `completed` / `errors` /
   `accepted`)SHALL be CPython-atomic reads + `write_lock` 保护文
   件 append。SHALL NOT race on concurrent jobs。

4. Heartbeat thread SHALL print + log_metric every 60s
   (`_STATUS_PRINT_INTERVAL_S`),包含 `active` / `completed` /
   `errors` / `queued`。

## 5. Metrics.jsonl logging

### 5.1 Two distinct paths

- **Service metrics**:`--metrics` flag,default `/tmp/gicg_eval_metrics.jsonl`,
  service-level events(started / heartbeat / job_done / job_fail)
- **Gauntlet results**:`result_path` per-request,training run 指定,
  append matchup JSONL entries

### 5.2 SHALL invariants

1. Each metrics line SHALL be valid JSON(no embedded newline),`kind`
   字段必填(`heartbeat` / `job_done` / `job_fail` / `started`)+
   `t`(uptime seconds)。

2. JSONL append SHALL be under `state.write_lock` 保护 — 多线程并
   发不损坏 line。

3. `--metrics` 接受 `None` → 禁 metrics 写(测试用)。

## 6. Paradigm-agnostic poll daemon — `tools/eval/daemon.py`

### 6.1 Architecture(transitional 新方向)

```
Mac side (eval daemon, async):
  Loop every --poll-seconds:
    1. rsync from --remote --run-label → local artifacts/<run-label>/
    2. Check local/latest.pt mtime; unchanged → continue
    3. Changed → load ckpt → build agent (paradigm adapter)
                → evaluator.run_once(agent)
                → append eval_metrics.jsonl + TB writer
```

Windows training side 不再 call in-process eval(`cfg.eval.enabled=False`),
ckpt 只 save + 不 eval。Mac 端 daemon 独立做 eval(同时也 read 训练
metrics.jsonl 用 tb 看 dual axis)。

### 6.2 SHALL invariants

1. Daemon SHALL be paradigm-agnostic — paradigm 选择由 `--paradigm`
   flag + `tools/eval/_paradigm.py::PARADIGMS` dict 注入。当前 shipped
   只 `dmc`,`az` / `cfr` reserved。

2. Paradigm adapter SHALL provide 5 keys:`load_config` / `build_agent`
   / `build_evaluator` / `build_baseline` / `ckpt_frame`,via
   `module:function` colon-separated string in `PARADIGMS` dict。

3. rsync SHALL be **whitelist-only**(`--include=latest.pt` +
   `ckpt_*.pt` + `metrics.jsonl` + `summary.json` + `tb/`),
   `--exclude=*` 兜底,防止 large file pollution。

4. Daemon SHALL `try / except / continue` 在 eval failure(network /
   rsync transient / load failure 不 crash daemon)— 但 SHALL print
   to stderr + 不 swallow exception type/message。

5. Ckpt frame extraction SHALL go through paradigm adapter
   (`ckpt_frame`),SHALL NOT 硬编码 dmc-specific blob field name。

## 7. Transitional state — legacy vs new

### 7.1 现状

- **Legacy socket daemon**(`tools/eval/eval_service.py`):AZ / CFR 训
  练栈用,production 稳定,gauntlet job 通过 socket dispatch
- **New poll daemon**(`tools/eval/daemon.py`):DMC Phase 3.5+ 用,
  rsync-based,paradigm-agnostic adapter,跨机训练(Windows train +
  Mac eval)场景

### 7.2 SHALL invariants(过渡期)

1. 二者 SHALL 并存,本 spec 同时治理。新 paradigm 接入时 SHALL 选
   一(不同时实现两套)。

2. 两 daemon SHALL NOT 互相 IPC — DMC 用 rsync + mtime,AZ/CFR 用
   socket,两套独立。

3. P2 后续 OpenSpec change 治理合并方案 — 是 socket daemon 接入
   paradigm adapter, 还是 poll daemon 接入 socket dispatch,by then
   决策。**本 spec 不 prescribe 合并方向**。

## 8. Cross-references

- [`./spec.md`](./spec.md) §3 SHALL 1 + SHALL 2 + SHALL 3 — service
  锚点
- [`./gauntlet.md`](./gauntlet.md) — `run_gauntlet_job` 内 dispatch
- [`./baselines.md`](./baselines.md) — player_spec oneOf schema
- [`training-architecture/eval`](../training-architecture/eval.md) —
  paradigm-agnostic eval inference 隔离

## 9. Status

- **Created**:2026-05-15(P1-T6)
- **Source**:`tools/eval/eval_service.py` + `tools/eval/eval_service_server.py`
  + `tools/eval/eval_service_job.py` + `tools/eval/daemon.py` +
  `tools/eval/_paradigm.py`
- **Known transitional state**:legacy socket daemon vs new poll
  daemon 并存。`eval_service_schema.json` pool/deck_padding silent
  fail follow-up(`memory project_v_phase2_eval_schema_gaps`)未完成。
