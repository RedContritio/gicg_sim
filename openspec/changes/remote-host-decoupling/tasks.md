---
last_updated: 2026-09-15
status: DRAFT
schema_version: 0
---

# Tasks — remote-host-decoupling

依赖链:`Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4`。Phase 1 是唯一有
设计判断的环节;Phase 2/3 是机械替换,但 Phase 3 的出口条件必须跑 `git grep`
复核,不能只靠逐处修改。

LOC 按 added/modified/deleted 估,不用时间单位。

**所有 `file:line` 均以本 change 落盘时的 `dev` HEAD 为基准**(`git rev-parse
HEAD` 时点)。实施时若目标文件已被本 change 前序任务改动(如 T1.2/T1.3 改
`_host.py`,`ruff format` 可能重排),行号会漂移 —— 以内容匹配为准,不要按数字
盲改。Phase 3 的出口判据是 `git grep` 归零,不是行号对上。

## Phase 0 — 交付前置(手工,一次性)

- [ ] **T0.1** 创建 `configs/hosts/hosts.toml`(gitignored),写入 `[gpu-win]`
      段的真实 `ssh` / `os` / `hostname` / `root` 四个值,其中
      `root = "D:/gicg_dev"`(56 上唯一的项目根;其余 4 个根已由用户手工删除)。
      **先 ssh 实测 56 的 `socket.gethostname()` 再填**,避免 design.md R1 的
      自转成环。— LOC 0(本地文件,不入库) — 依赖:无
- [ ] **T0.2** 确认 `.gitignore` 新增 `configs/hosts/hosts.toml`,且
      `git status` 不显示该文件。— LOC 1 — 依赖:T0.1

## Phase 1 — 解析层

- [ ] **T1.1** `configs/hosts/hosts.example.toml`(tracked 模板,占位符值,
      含 `root = "D:/project"`)。— LOC ~9(新增)— 依赖:无
- [ ] **T1.2** `tools/runs/_host.py`:新增 `HOST_REGISTRY` 常量 +
      `load_host_registry(path) -> dict[str, RemoteCfg]`;重写
      `load_remote_from_cfg` 按 design.md §1.3 契约解析——cfg 侧只读
      `[remote].profile`,四字段的校验迁到注册表条目上(`RemoteCfg` 形状不变)。
      — LOC ~60(modify)— 依赖:T1.1
- [ ] **T1.3** `tools/runs/_host.py` docstring:第 3–17 行的示例块改用
      `profile` + 占位符形式,去掉真实 IP。— LOC ~15(modify)— 依赖:T1.2
- [ ] **T1.4** `tools/runs/_remote_sync.py`:`_auto_sync` 构造 `paths` 处
      (:181-186)无条件并入注册表(相对路径 `configs/hosts/hosts.toml`)。**不加
      存在性判断** —— `main()` / `build_engine` 都先经 `load_remote_from_cfg`,
      缺失时已 raise,该判断是死分支。**也不改成"仅首同步并入"** —— 远端只读
      `hostname`,无条件推使"改注册表"即为充分修复动作;仅首同步会让远端陈旧,
      且无法通过改注册表修复(design.md §1.4、R1)。`--tar-all` 不必改(目录遍历
      已含),`--single` 不得改(单文件契约)。副作用:第 207 行 "nothing to push"
      快速路径不再触发。— LOC ~5 — 依赖:T1.2
- [ ] **T1.5** **新建** `tools/runs/tests/test_host_registry.py`,把
      `test_host_cfg.py` 中 `load_remote_from_cfg` 的全套测试
      (happy/sad paths :34-185 + P4 补丁三条 :379-405,约 179 行)整体迁入并
      改造为 `profile` + tmp 注册表(`registry_path` 注入)。按 design.md §1.3 表
      逐条补 `pytest.raises`:`[remote].profile` 缺失/空、注册表文件不存在、
      profile 名不存在、注册表条目内 `ssh` 空 / `hostname` 空 / `os` 非法 /
      `root` 缺失。
      `test_host_cfg.py` 迁后约 227 行,保留 `RemoteCfg` / `is_local_host` /
      `discover_remote_*`。**不选原地扩写** —— 该文件已 406 行、限额 500,原地
      扩写约 +112 行会撞 pre-commit 的 line-limit hook。— LOC ~130(test,
      净迁移)— 依赖:T1.2
- [ ] **T1.6** 改 `tools/experiments/tests/test_native_starter_config.py:18`:
      断言 `load_remote_from_cfg(...).ssh == 'dev@192.168.31.56'` 改为基于 tmp
      注册表 fixture 断言 profile 解析结果。— LOC ~10 — 依赖:T1.2
- [ ] **T1.7** **确认**(非修改)`RemoteCfg` 数据类形状不变(仍是
      `ssh`/`root`/`os`/`hostname` 四字段),故直接构造 `RemoteCfg(...)` 的
      5 个测试文件无需改动:`test_dispatch_misc.py`、`test_pull_modes.py`、
      `test_remote_sync_deletion.py`、`test_ssh_forward.py`、
      `test_tail_args.py`(全部用合成值 `dev@x` / `OTHER-PC` 等)。
      真正需要改的 `load_remote_from_cfg` 调用方只有
      `test_host_cfg.py` 中那一套(迁往 T1.5 的新文件)与
      `test_smoke_remote.py`(见 T3.5)。— LOC 0 — 依赖:T1.2

## Phase 2 — cfg 迁移

- [ ] **T2.1** 14 个 `configs/dmc/*.toml` 的 `[remote]` 段:四字段
      (`ssh` / `root` / `os` / `hostname`)整体删除,只留 `profile = "gpu-win"`
      一行。各文件原来写的 `root`(共 5 种取值)一并收敛到注册表内的
      `D:/gicg_dev`,**不逐个保留** —— 它们是 design.md §1.1 的执行期漂移,且其中
      4 个指向已删目录。迁移后 `[remote]` 段只剩 `profile`。
      — LOC ~70(14 × (删 4 / 加 1))— 依赖:T1.2

## Phase 3 — HEAD 脱敏

替换表:`192.168.31.56` → `192.0.2.10`(**裸 host,不得带 `user@`** —— 该标识
实测几乎全部嵌在 `dev@<IP>` / `user@<IP>` 里,替换是就地子串替换,带 `user@`
会产出 `dev@dev@host` 这类畸形目标;依据 design.md §T4);
`DESKTOP-GHJCC7Q` → `DEV-PC`;`Mac-mini.local` → `macbox.local`。

- [ ] **T3.1** `docs/` **10 个文件 14 处**:`0_status/README.md:66`、
      `0_status/remote-training-reset-2026-09-11.json:2`、
      `3_plans/backlog.md:81,87`、**`3_plans/cards/native_first_batch_audit.md:246`**、
      `5_history/dmc_phase35_infra.md:26`、
      `5_history/dmc_phase35_infra_impl/01_remote.md:23,30,65`、
      `5_history/dmc_phase35_infra_impl/03_eval.md:384`、
      `5_history/handoff_20260914_part3.md:12,14`、
      `5_history/small_rl_v14.md:13`、
      `superpowers/specs/2026-05-18-tools-runs-redesign-design.md:184`。
      `0_status/README.md` 是 LIVE 文档,指引改为指向 `hosts.example.toml`。
      — LOC ~20 — 依赖:T2.1
- [ ] **T3.2** `openspec/changes/archive/` **3 个文件 4 处**:
      `core-network-generic-promotion/design/architecture.md:159,162`、
      `i29-go-actor-pool/STATE_DUMP_2026_05_24.md:57`、
      `i29-go-actor-pool/shminf_win_build.md:8`。
      — LOC ~6 — 依赖:T2.1
- [ ] **T3.3** `training/paradigms/dmc/PLAN.md:735,744,746`(3 处)、
      `notes.md:343,429,432,477,480`(5 处)。— LOC ~10 — 依赖:T2.1
- [ ] **T3.4** `tools/_bench/p2_results/` **12 个文件**,全部在第 5 行、形状统一为
      `Box: dev@192.168.31.56 (DESKTOP-GHJCC7Q, …)`:PEAK_WIN_ACCEPTANCE /
      PEAK_WIN_ROOT_CAUSE / peak_win_n12_16_20_3seed / sanity_win_n4 /
      sanity_win_n4_v2 / scan_win_n4_32_1seed / win_fine_n_python_mp_5seed /
      win_fine_n_sweep_5seed / win_fine_n_sweep_5seed_expand /
      win_gomaxprocs_n16_5seed / win_gomaxprocs_sweep_n16 /
      win_runtime_sweep_n19(`.md`)。该行由 T3.6 的生成器写出,故 T3.6 完成后
      新报告自动干净。— LOC ~12 — 依赖:T2.1
- [ ] **T3.5** 其余代码内标识:`tools/eval/daemon.py:15,138` 与
      `tools/runs/sync.py:178` 的 help/注释示例改中性值;
      `tools/runs/tests/test_smoke_remote.py:8` 的 docstring;
      **`tools/runs/tests/test_schema.py:31`**(`host='Mac-mini.local'` 测试
      fixture);**`tools/runs/tests/test_sync_ipv6.py:54`**
      (`'user@192.168.31.56:/d/gicg_dev/'` 样例串)。
      — LOC ~10 — 依赖:T2.1
- [ ] **T3.6** `tools/_bench/run_win_collector_pair.py`:删 `_WIN_SSH`(:40)/
      `_WIN_ROOT`(:41)常量,改注册表解析(`--host-profile`,默认 `gpu-win`);
      :3 的 docstring 与 :158 的输出行同步。— LOC ~20 — 依赖:T1.2
- [ ] **T3.6b** `configs/dmc/eval_stage3_b_v_legacy.toml:8` —— 该文件**没有**
      `[remote]` 段,唯一命中是注释里的示例命令,故不在 T2.1 的 14 个之列,
      在此单独替换。— LOC ~1 — 依赖:T2.1
- [ ] **T3.7** `git grep` 复核:三项标识在 HEAD 内零残留(区分大小写;同时
      确认 `/Users/redcontritio`、`RedContritio`、`D:/gicg_*` 按 Out of scope
      保留)。出口判据:`git grep -cI` 各目录计数由
      `configs/` 15 / `tools/` 20 / `docs/` 10 / `openspec/` 3 / `training/` 2
      全部归零(合计 50 文件 / 78 处 → 0)。— 依赖:T3.1–T3.6b

## Phase 4 — 验证

- [ ] **T4.1** 本机:`pytest -n 4 gicg_env/tests/ training/tests/ tools/runs/tests/
      tools/eval/tests/` 全绿。— 依赖:T1–T3
- [ ] **T4.2** 四项 pre-commit 检查:`check_line_limits` 零违规
      (`tools/_meta/check_line_limits.py` 全仓审计)、`ruff format --check`、
      `gofmt -l` 无输出、`check_openspec_indices` 退出 0。— 依赖:T1–T3
- [ ] **T4.3** 确认 `fingerprint()` 仍为
      `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15`
      ——验证 design.md §1.5 的指纹中性主张。若已变,说明碰到了
      `data/**/*.{lua,toml}`、`gicg_engine/**/*.go`、`gicg_env/**/*.py`、
      `training/{core,paradigms}/**/*.py` 之一,须回退那处改动,而非改文档迎合。
      — 依赖:T4.2
- [ ] **T4.4** 确认**无需**改文档指纹记录。指纹值仅出现在 3 个文件 4 处
      (`docs/0_status/README.md` ×2、`docs/HANDOFF.md` ×1、
      `docs/HANDOFF_PAUSED.md` ×1),因 T4.3 主张不变。若 T4.3 发现指纹已变,
      说明设计前提被破坏,应回退而非改文档迎合。— LOC 0 — 依赖:T4.3
- [ ] **T4.5** **远端 e2e 门槛(设备开机后)**:`tools.runs.train
      configs/dmc/native_starter.toml` 端到端派发到 56 并跑通,含首次全量同步
      把注册表带过去。这是本 change 的真验收——前三项检查只证明代码自洽,
      不证明远端派发路径可用。依据:memory `feedback_tool_production_smoke_required`
      (工具类 spec 止步于 mock 是 anti-pattern)。— 依赖:T4.1–T4.4 + 设备可用

## 验收出口

`T4.1`–`T4.4` 可在设备关机期间完成;`T4.5` 不可。**在 T4.5 通过之前,本 change
不得 archive**——`tools-layout` 的 #17 是活规约,而远端派发路径未经验证。
