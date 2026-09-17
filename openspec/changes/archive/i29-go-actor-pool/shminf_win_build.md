# SHMRing Path A Phase 4 — Win box build + smoke steps

Date: 2026-05-24
Branch: `feature/i29-go-actor-shminf` (Phase 4 commit pending user review)

## 前置

- Win box: DEV-PC (9950X3D + 5070 Ti), `D:\gicg_dev`
- 工具链(已装):Go 1.26.x, Strawberry Perl gcc (`C:\Strawberry\c\bin\gcc.exe`),
  Python 3.13/3.14 venv with torch 2.12+cu130
- SHM 自身不需要额外依赖 — kernel32 是 system DLL，CreateFileMapping /
  MapViewOfFile 等都 ship 在 Win 上;`gcc` 已有

## Step 1 — sync branch

在 Win box PowerShell:

```powershell
cd D:\gicg_dev
git fetch origin
git checkout feature/i29-go-actor-shminf
git pull
```

## Step 2 — build C-shared libs

```powershell
$env:CGO_ENABLED = "1"
$env:CC = "C:\Strawberry\c\bin\gcc.exe"
$env:PATH = "C:\Strawberry\c\bin;" + $env:PATH

# Engine + actor (这两个跟之前一样)
go build -buildmode=c-shared -o gicg_env\libgicg.dll       .\gicg_engine\capi
go build -buildmode=c-shared -o gicg_env\libgicg_actor.dll .\gicg_actor\capi
```

Phase 4 加进来的 SHM 后端 `shm_win.c` 由 cgo 自动 pick(同包内 `.c` 全部编),
不需要单独 build。

## Step 3 — Python libshm.dll auto-build smoke

Python 端 `CrossLangShmRing` 首次 attach 时若 `libshm.dll` 不存在,会自动
`gcc -shared -O2 shm_win.c -lkernel32` 现编一份到 `gicg_actor/shm/libshm.dll`。
触发一次确认:

```powershell
.venv\Scripts\python -c "from training.core.actor.ipc.ring_shm import CrossLangShmRing; r = CrossLangShmRing('phase4_smoke', 4, 64, create=True); r.close(); print('OK')"
```

期望:输出 `OK`,且 `gicg_actor\shm\libshm.dll` 出现。

## Step 4 — unit tests

### Go side

```powershell
go test .\gicg_actor\shm\... -v -count=1                  # cross-platform shm tests
go test .\gicg_actor\ -v -count=1 -run "TestInferenceShmClient"  # in-process roundtrip
go test .\gicg_actor\ -v -count=1 -run "TestStartPool_ShmMode"   # pool wiring
```

Phase 1-3 已通过的 Mac/Linux 测试在 Win 上跑同一份代码 — 重点在 Win path
是否能复用同一 test 文件 (build tag 已从 `!windows` 改为三平台共通)。

### Python side

```powershell
.venv\Scripts\python -m pytest training\core\actor\ipc\tests\test_ring_shm.py -v
```

期望:23 tests PASS (Mac/Linux 同步)。

## Step 5 — SHM e2e smoke (key gate)

```powershell
.venv\Scripts\python -m pytest training\core\actor\tests\test_go_actor_perf_smoke_shm.py -m smoke_full -s
```

Mac 端 Phase 3 已 PASS。 Win 端这是 Phase 4 验收 gate。

## Step 6 — N=16 perf bench (true Phase 4 victory condition)

Phase 4 ship 的目标:Win box SHM path fps ≥ Python mp 35-37。 跑同 commit
benchmark:

```powershell
# Go-actor + SHM
.venv\Scripts\python -m tools._bench.win_n16_fair --backend go-actor-shm

# Python mp baseline (已有数据)
.venv\Scripts\python -m tools._bench.win_n16_fair --backend python-mp
```

(bench harness 已在 `tools/_bench/`,加 `--backend` flag 可能要小改;若 cfg 已支持
`InferenceShmMode` 直接 toggle 即可。)

## 已知 caveat

1. **Python `SharedMemory` Win naming**: CPython 3.8+ 在 Win 把 user-supplied
   name 透传给 `CreateFileMapping`,不加前缀。 Phase 4 验证过 CPython
   `Lib/multiprocessing/shared_memory.py` 源码;`wnsm_` 前缀只出现在
   auto-generated name (即 `SharedMemory(name=None)`)。 user 显式传 name 时
   Go 端 `OpenFileMappingA(<bare name>)` 直接命中。

2. **gcc on PATH**: Python 自动 build libshm.dll 需要 `gcc` 在 PATH。 Strawberry
   Perl 装的 gcc 已经在 PATH。 若用 MSYS2 / 其他 mingw-w64,确认 `where gcc`
   能找到。

3. **`/tmp` 路径不存在**: 之前 ring_shm.py 的 lib 搜索路径含 `/tmp`,Win 上无
   `/tmp`;Phase 4 已清掉,只保留 `gicg_actor/shm/` + `gicg_env/`。

4. **MSVC vs MinGW ABI**: cgo on Win 默认走 mingw gcc。 我们的 `_build_shm_lib`
   也强制用 gcc(不用 MSVC),避免 struct padding edge case 把 Python ctypes
   与 Go cgo 看到的 layout 错开。 若 user 改装 LLVM/clang 走 MSVC ABI,需要
   补 `_Static_assert(sizeof(ShmRingHeader) == 64)` 提前发现差异(已加)。

5. **kernel object lifetime**: Win 没有 `shm_unlink` 等价物;kernel object 由
   HANDLE 引用计数管。 Python `SharedMemory.unlink()` 是 no-op,本地代码 path
   `shm_unlink_name()` 在 Win 也是 no-op。 实际 cleanup 全靠 close handle —
   Python 端 SharedMemory.close + Go 端 shm.Ring.Close 都走完即可。

## Phase 4 LOC ledger

| 文件 | 类型 | LOC | 说明 |
|------|------|-----|------|
| `gicg_actor/shm/shm_win.c` | new | 418 | Win SHM impl (CreateFileMapping + MapViewOfFile + C11 atomics + HANDLE table) |
| `gicg_actor/shm/shm_windows.go` | new | 286 | Win cgo binding (mirrors shm.go API) |
| `gicg_actor/shm/shm_unix.c` | modify | +5 | `#ifndef _WIN32` whole-file guard |
| `gicg_actor/shm/shm_ring.h` | modify | +18 | 三平台 doc + platform-aware naming note |
| `gicg_actor/shm/shm.go` | modify | +7 | doc tweak (Phase 4 reference) |
| `gicg_actor/shm/shm_test.go` | modify | +13 | drop `!windows` tag; `isWindows` gate for NormaliseName |
| `gicg_actor/inference_shm_client.go` | modify | +6 / -3 | drop `!windows` tag |
| `gicg_actor/inference_shm_client_test.go` | modify | +4 / -2 | drop `!windows` tag |
| `gicg_actor/inference_shm_client_windows.go` | delete | -36 | stub replaced by real impl |
| `gicg_actor/pool.go` | modify | +2 / -1 | doc tweak |
| `gicg_actor/pool_shm_test.go` | modify | +2 / -3 | drop `!windows` tag |
| `training/core/actor/ipc/ring_shm.py` | modify | +24 / -10 | Win path: lib build, name passthrough |
| `training/core/actor/ipc/tests/test_ring_shm.py` | modify | +8 / -3 | Win gate via `shutil.which('gcc')` instead of skip |
| **Total** | | ~770 new + ~30 net modify | Win path full e2e support |

## Verification status (本 session)

| Check | Mac | Linux | Win |
|-------|-----|-------|-----|
| Mac build `go build ./gicg_actor/...` | PASS | — | — |
| Mac `go test ./gicg_actor/...` 全 PASS | PASS | — | — |
| Mac `pytest training/core/actor/ipc/` 全 PASS | 23 PASS | — | — |
| `clang -fsyntax-only` with fake windows.h on `shm_win.c` | PASS (clean) | — | — |
| `GOOS=windows go list` confirms file selection | PASS | — | — |
| Win box build + run | — | — | **TODO user** |
