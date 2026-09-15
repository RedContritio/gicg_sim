> 分卷导航:回到 [← Part 1](2026-05-18-tools-runs-second-round-fixes.md) · [← Part 2](2026-05-18-tools-runs-second-round-fixes-part2.md)

## Phase 4: M7 invariant consolidation

### Task 4.1: 删除 show/list 的 invariant,挪到 `schema.load_file`

**Files:**
- Modify: `tools/runs/schema.py` (`load_file`)
- Modify: `tools/runs/show.py` (remove redundant block)
- Modify: `tools/runs/list.py` (remove redundant block)
- Modify: `tools/runs/tests/test_show_smoke.py` + `test_list_smoke.py` (tests still pass via schema)

- [ ] **Step 1: Update schema.load_file to enforce invariant**

In `tools/runs/schema.py`, replace `load_file`:

```python
def load_file(path: Path) -> RunMetadata:
    """Load + validate. Also enforces M7 filename invariant:
    `path.stem` MUST equal `meta.run_id` (a hand-rename or copy-paste
    mislabel is corruption, not a legitimate query miss)."""
    meta = loads(path.read_text(encoding='utf-8'))
    if meta.run_id != path.stem:
        raise ValueError(
            f'metadata at {path} has run_id={meta.run_id!r} != filename stem {path.stem!r} '
            f'(file mislabeled)'
        )
    return meta
```

- [ ] **Step 2: Remove redundant check in show.py**

In `tools/runs/show.py:main()`, **delete** the block:

```python
    # M7 invariant: filename stem must match internal run_id; a hand-
    # edited or copy-paste mislabeled file is corruption, not a query miss.
    if meta.run_id != args.run_id:
        print(
            f'tools.runs.show: file {path} internal run_id={meta.run_id!r} '
            f'!= requested {args.run_id!r}; file mislabeled',
            file=sys.stderr,
        )
        return 1
```

The existing `except (ValueError, OSError)` around `schema.load_file(path)` now catches the new invariant raise — but the error message is slightly different. Verify the show mislabeled test still asserts something present in the new message ("mislabeled" word is in the new schema message, so existing assertion holds).

- [ ] **Step 3: Remove redundant check in list.py**

In `tools/runs/list.py:_collect`, **delete** the block:

```python
        # M7 invariant: filename stem must equal internal run_id; otherwise
        # `show <run_id>` opens a different file than `list` reports.
        if p.stem != meta.run_id:
            print(
                f'tools.runs.list: skipping {p.name}: filename stem {p.stem!r} '
                f'!= metadata.run_id {meta.run_id!r}',
                file=sys.stderr,
            )
            continue
```

The existing `except (ValueError, OSError) as e:` around `schema.load_file(p)` now catches the new invariant ValueError and skips with stderr message. Update the test expectation if needed.

- [ ] **Step 4: Update test_list_smoke.py assertion**

In `tools/runs/tests/test_list_smoke.py::test_list_skips_mislabeled_file`, the existing assertion:

```python
    assert "metadata.run_id 'r013'" in captured.err
```

…now reads metadata via schema.load_file which raises with a slightly different message. Update assertion to match new wording:

```python
    assert 'mislabeled' in captured.err
    assert 'r013' in captured.err  # internal run_id still mentioned
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 113 PASS (no regression — invariant moved, not lost).

- [ ] **Step 6: Commit**

```bash
git add tools/runs/schema.py tools/runs/show.py tools/runs/list.py tools/runs/tests/test_show_smoke.py tools/runs/tests/test_list_smoke.py
git commit -m "tools/runs: consolidate M7 filename invariant into schema.load_file (LOW 2)"
```

---

## Final Verification

### Task F.1: Full sweep + ruff + integration

- [ ] **Step 1: All test tiers**

```bash
.venv/bin/python -m pytest tools/runs/tests/ -q
.venv/bin/python -m pytest tools/tests/ -q
.venv/bin/python -m pytest -m smoke training/tests/ -q
.venv/bin/python -m pytest -m integration tools/runs/tests/ -v
.venv/bin/ruff format --check tools/runs/ tools/run.py training/core/checkpoint.py training/core/pipeline.py training/core/config/loader.py
```

Expected:
- tools/runs/tests/: 113 PASS
- tools/tests/: 3 PASS (new file from Phase 2/3)
- -m smoke: 5/5 paradigm PASS
- -m integration: 2-3 PASS (local rsync + mtime-tie always; ssh-localhost depending on env)
- ruff: 0 reformats

- [ ] **Step 2: End-to-end production sanity**

Manually verify the full new lifecycle:

```bash
# clean
rm -f artifacts/runs/s999.toml

# register
.venv/bin/python -m tools.runs.register --run-id s999 --cfg configs/dmc/smoke_full.toml --type s --label dmc_phase4_sanity --description "phase 1-4 sanity"

# train (timestamp single-sourced UTC + auto-complete)
.venv/bin/python -m tools.run configs/dmc/smoke_full.toml --max-steps 5 --run-id s999

# verify metadata closed loop
.venv/bin/python -m tools.runs.show s999 | grep -E 'status|artifacts_dir|cfg_run_label'
```

Expected output includes:
- `status       : done`
- `artifacts_dir: artifacts/<UTC_ts>_dmc_smoke_full`(`<UTC_ts>` matches `metadata.timestamp` converted to UTC strftime)
- `cfg_run_label: dmc_smoke_full`

---

## Self-Review

### 1. Spec coverage

12 缺陷 ↔ task mapping:

| # | 缺陷 | Task |
|---|---|---|
| HIGH 1 | cross-tz astimezone | Task 3.1 |
| HIGH 2 | smoke_full 未接 --run-id | Task 3.3(文档化 scope,不强制注入) |
| MED 1 | underscore promote | Task 1.1 |
| MED 2 | cfg_run_label vs override | Task 2.1 + 2.2 |
| MED 3 | complete 必手填 | Task 3.2(auto-complete) |
| MED 4 | sync `:` validate | Task 1.6 |
| MED 5 | symlink resolve | Task 1.7(文档化) |
| LOW 1 | NaN allow | Task 1.2 |
| LOW 2 | show invariant 冗余 | Task 4.1 |
| LOW 3 | schema docstring | Task 1.3 |
| LOW 4 | backlog I10 | Task 1.4 |
| LOW 5 | mtime-tie test | Task 1.5 |

12/12 covered。

### 2. Placeholder scan

- 没有 "TBD" / "implement later" / "add appropriate error handling"
- Task 3.2 integration test 的 cfg 是完整 inline TOML(无 `...similar to`)
- 每个 code-changing step 都有 actual code block

### 3. Type / name consistency

- `cfg_run_label_override` Task 2.1 register signature + CLI flag dest + body 检查 都用同一名 ✓
- `_metadata_timestamp_to_dir_prefix` Task 3.1 helper 名 + import 一致 ✓
- `complete_from_train` Task 3.2 函数名 + import + 调用一致 ✓
- `load_with_extends` Task 1.1 rename 后所有 site 同名 ✓

---

## Execution Notes

- **Phase ordering**:Phase 1 任务彼此独立,可任意顺序;Phase 2 → Phase 3 单向(Task 3.1 复用 helper,Task 3.2 复用 register flag);Phase 4 独立,可放最后
- **Commit cadence**:每个 Task 一个 commit(per CLAUDE.md §4),18 commits total
- **不要 squash**:每个 task 是一个完整改动单元,squash 会丢 audit trail
- **若 Phase 3 Task 3.2 integration test 超时**:可改 `--max-steps 3` 进一步缩短(DMC 3 step ≤ 3s);或将 test 标 `@pytest.mark.smoke_full` 移出默认 collection
